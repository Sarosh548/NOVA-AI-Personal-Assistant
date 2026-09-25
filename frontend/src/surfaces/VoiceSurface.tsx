import { useCallback, useEffect, useRef, useState } from "react"

import { ApiRequestError, getAccessToken, refreshAccessToken } from "../api/client"
import { API_BASE_URL } from "../app/config"
import { Icon } from "../components/Icon"

type VoiceState =
  | "connecting"
  | "ready"
  | "listening"
  | "thinking"
  | "speaking"
  | "reconnecting"
  | "disconnected"

const TARGET_SAMPLE_RATE = 16_000
const TARGET_CHANNELS = 1
const TARGET_ENCODING = "pcm_s16le"

const PCM_WORKLET_SOURCE = `
class NovaPcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.active = false
    this.buffer = new Float32Array(0)
    this.position = 0
    this.targetRate = 16000
    this.chunkSize = 320

    this.port.onmessage = (event) => {
      if (event.data && event.data.type === "set-active") {
        this.active = Boolean(event.data.active)
        if (!this.active) {
          this.buffer = new Float32Array(0)
          this.position = 0
        }
      }
    }
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel) return true

    if (!this.active) {
      return true
    }

    const merged = new Float32Array(this.buffer.length + channel.length)
    merged.set(this.buffer)
    merged.set(channel, this.buffer.length)
    this.buffer = merged

    const step = sampleRate / this.targetRate

    while (
      this.position + (this.chunkSize - 1) * step <
      this.buffer.length
    ) {
      const pcm = new Int16Array(this.chunkSize)

      for (let index = 0; index < this.chunkSize; index += 1) {
        const position = this.position + index * step
        const leftIndex = Math.floor(position)
        const fraction = position - leftIndex
        const left = this.buffer[leftIndex] || 0
        const right = this.buffer[leftIndex + 1] ?? left
        const sample = Math.max(
          -1,
          Math.min(1, left + (right - left) * fraction),
        )

        pcm[index] = sample < 0
          ? sample * 0x8000
          : sample * 0x7fff
      }

      this.position += this.chunkSize * step

      const consumed = Math.floor(this.position)
      if (consumed > 0) {
        this.buffer = this.buffer.slice(consumed)
        this.position -= consumed
      }

      this.port.postMessage(pcm.buffer, [pcm.buffer])
    }

    return true
  }
}

registerProcessor("nova-pcm-processor", NovaPcmProcessor)
`

function buildVoiceWebSocketUrl(): string {
  if (!API_BASE_URL) {
    throw new Error("NOVA API endpoint is not configured.")
  }

  const protocolUrl = API_BASE_URL.replace(/^http/, "ws")
  return `${protocolUrl}/voice/ws`
}

function requestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `nova-voice-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function formatError(error: unknown, fallback: string): string {
  return error instanceof ApiRequestError ? error.detail : fallback
}

function pcmToAudioBuffer(
  audioContext: AudioContext,
  payload: ArrayBuffer,
): AudioBuffer | null {
  if (payload.byteLength < 2) return null

  const samples = new Int16Array(payload)

  if (samples.length === 0) return null

  const buffer = audioContext.createBuffer(
    TARGET_CHANNELS,
    samples.length,
    TARGET_SAMPLE_RATE,
  )
  const channel = buffer.getChannelData(0)

  for (let index = 0; index < samples.length; index += 1) {
    channel[index] = samples[index] < 0
      ? samples[index] / 0x8000
      : samples[index] / 0x7fff
  }

  return buffer
}

export function VoiceSurface({
  onOpenConversation,
}: {
  onOpenConversation: () => void
}) {
  const [state, setState] = useState<VoiceState>("connecting")
  const [transcript, setTranscript] = useState("")
  const [response, setResponse] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [audioState, setAudioState] = useState<"idle" | "preparing" | "playing">("idle")
  const [audioChunkCount, setAudioChunkCount] = useState(0)
  const [audioByteCount, setAudioByteCount] = useState(0)
  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine,
  )

  const socketRef = useRef<WebSocket | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const micStreamRef = useRef<MediaStream | null>(null)
  const micSourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const workletRef = useRef<AudioWorkletNode | null>(null)
  const muteGainRef = useRef<GainNode | null>(null)
  const playbackGainRef = useRef<GainNode | null>(null)
  const playbackSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set())
  const playbackEndTimeRef = useRef(0)
  const playbackTimerRef = useRef<number | null>(null)
  const playbackEventChainRef = useRef<Promise<void>>(Promise.resolve())
  const playbackGenerationRef = useRef(0)
  const autoListenTimerRef = useRef<number | null>(null)
  const turnIdRef = useRef<string | null>(null)
  const sessionReadyRef = useRef(false)
  const intentionalCloseRef = useRef(false)
  const reconnectingRef = useRef(false)
  const authRecoveryAttemptedRef = useRef(false)
  const assistantAudioFinalRef = useRef(false)
  const pingTimerRef = useRef<number | null>(null)
  const workletUrlRef = useRef<string | null>(null)
  const startTurnRef = useRef<(() => Promise<void>) | null>(null)
  const scheduleAutoListenRef = useRef<(() => void) | null>(null)

  const clearPlaybackTimer = () => {
    if (playbackTimerRef.current !== null) {
      window.clearTimeout(playbackTimerRef.current)
      playbackTimerRef.current = null
    }
  }

  const clearAutoListenTimer = useCallback(() => {
    if (autoListenTimerRef.current !== null) {
      window.clearTimeout(autoListenTimerRef.current)
      autoListenTimerRef.current = null
    }
  }, [])

  const stopPlayback = useCallback(() => {
    clearPlaybackTimer()
    clearAutoListenTimer()
    playbackGenerationRef.current += 1
    playbackEventChainRef.current = playbackEventChainRef.current.then(() => undefined)
    for (const source of playbackSourcesRef.current) {
      try {
        source.stop()
      } catch {
        // The source may already have ended.
      }
    }
    playbackSourcesRef.current.clear()
    playbackEndTimeRef.current = 0
    assistantAudioFinalRef.current = false
    setAudioState("idle")
  }, [clearAutoListenTimer])

  const ensureAudioOutput = useCallback(async () => {
    const audioContext = audioContextRef.current ?? new AudioContext()
    audioContextRef.current = audioContext
    await audioContext.resume()

    if (!playbackGainRef.current) {
      const playbackGain = audioContext.createGain()
      playbackGain.gain.value = 1
      playbackGain.connect(audioContext.destination)
      playbackGainRef.current = playbackGain
    }

    if (audioContext.state !== "running") {
      throw new Error(
        "Browser audio output is not active. Click the NOVA voice button once to enable audio."
      )
    }

    return audioContext
  }, [])

  const setCaptureActive = useCallback((active: boolean) => {
    if (workletRef.current) {
      workletRef.current.port.postMessage({
        type: "set-active",
        active,
      })
    }
  }, [])

  const deactivateCapture = useCallback(() => {
    turnIdRef.current = null
    setCaptureActive(false)
  }, [setCaptureActive])

  const releaseAudioCapture = useCallback(() => {
    deactivateCapture()

    if (workletRef.current) {
      workletRef.current.disconnect()
      workletRef.current = null
    }

    if (micSourceRef.current) {
      micSourceRef.current.disconnect()
      micSourceRef.current = null
    }

    if (muteGainRef.current) {
      muteGainRef.current.disconnect()
      muteGainRef.current = null
    }

    if (playbackGainRef.current) {
      playbackGainRef.current.disconnect()
      playbackGainRef.current = null
    }

    if (micStreamRef.current) {
      for (const track of micStreamRef.current.getTracks()) {
        track.stop()
      }
      micStreamRef.current = null
    }
  }, [deactivateCapture])

  const closeSocket = useCallback(() => {
    if (pingTimerRef.current !== null) {
      window.clearInterval(pingTimerRef.current)
      pingTimerRef.current = null
    }

    sessionReadyRef.current = false
    reconnectingRef.current = false
    intentionalCloseRef.current = true
    clearAutoListenTimer()
    releaseAudioCapture()
    stopPlayback()

    const socket = socketRef.current
    socketRef.current = null

    if (socket && socket.readyState === WebSocket.OPEN) {
      try {
        socket.send(JSON.stringify({ type: "session.close" }))
      } catch {
        // The close frame below still terminates the session.
      }
    }

    if (socket && socket.readyState !== WebSocket.CLOSED) {
      socket.close()
    }
  }, [
    clearAutoListenTimer,
    releaseAudioCapture,
    stopPlayback,
  ])

  const connect = useCallback(async (recovery = false) => {
    if (!online || reconnectingRef.current) return

    const token = getAccessToken()
    if (!token) {
      setState("disconnected")
      setError("Your NOVA session is no longer available. Please sign in again.")
      return
    }

    reconnectingRef.current = true
    intentionalCloseRef.current = false
    sessionReadyRef.current = false
    setState(recovery ? "reconnecting" : "connecting")
    setError(null)

    const existing = socketRef.current
    if (existing && existing.readyState !== WebSocket.CLOSED) {
      existing.close()
    }

    let socket: WebSocket
    try {
      socket = new WebSocket(buildVoiceWebSocketUrl())
      socket.binaryType = "arraybuffer"
    } catch (err) {
      reconnectingRef.current = false
      setState("disconnected")
      setError(formatError(err, "NOVA voice could not connect."))
      return
    }

    socketRef.current = socket

    socket.onopen = () => {
      if (socketRef.current !== socket) {
        socket.close()
        return
      }

      reconnectingRef.current = false
      const currentToken = getAccessToken()

      if (!currentToken) {
        setError("Your NOVA session is no longer available. Please sign in again.")
        socket.close(1008, "Authentication required")
        return
      }

      socket.send(
        JSON.stringify({
          type: "session.authenticate",
          access_token: currentToken,
        }),
      )
    }

    socket.onmessage = async (event) => {
      if (socketRef.current !== socket) return

      if (typeof event.data !== "string") {
        const payload =
          event.data instanceof ArrayBuffer
            ? event.data
            : await event.data.arrayBuffer()

        setAudioChunkCount((count) => count + 1)
        setAudioByteCount((count) => count + payload.byteLength)

        const generation = playbackGenerationRef.current

        playbackEventChainRef.current = playbackEventChainRef.current.then(
          async () => {
            if (
              socketRef.current !== socket ||
              playbackGenerationRef.current !== generation ||
              intentionalCloseRef.current
            ) {
              return
            }

            let audioContext: AudioContext
            try {
              audioContext = await ensureAudioOutput()
            } catch (err) {
              setAudioState("idle")
              setError(
                formatError(
                  err,
                  "NOVA could not activate browser audio output.",
                ),
              )
              return
            }

            const buffer = pcmToAudioBuffer(audioContext, payload)
            if (!buffer) return

            if (!playbackGainRef.current) {
              setAudioState("idle")
              setError("NOVA audio output is unavailable.")
              return
            }

            const source = audioContext.createBufferSource()
            source.buffer = buffer
            source.connect(playbackGainRef.current)
            source.onended = () => {
              playbackSourcesRef.current.delete(source)

              if (
                playbackSourcesRef.current.size === 0 &&
                playbackEndTimeRef.current <= audioContext.currentTime + 0.03
              ) {
                setAudioState("idle")

                if (
                  assistantAudioFinalRef.current &&
                  turnIdRef.current === null &&
                  sessionReadyRef.current &&
                  !intentionalCloseRef.current
                ) {
                  scheduleAutoListenRef.current?.()
                } else {
                  setState((current) =>
                    current === "speaking" ? "ready" : current,
                  )
                }
              }
            }

            const startAt = Math.max(
              audioContext.currentTime + 0.015,
              playbackEndTimeRef.current,
            )

            source.start(startAt)
            playbackEndTimeRef.current = startAt + buffer.duration
            playbackSourcesRef.current.add(source)
            setAudioState("playing")
            setState("speaking")
          },
        ).catch((err) => {
          setAudioState("idle")
          setError(
            formatError(
              err,
              "NOVA could not play the voice response.",
            ),
          )
        })

        await playbackEventChainRef.current
        return
      }

      let payload: Record<string, unknown>
      try {
        payload = JSON.parse(event.data) as Record<string, unknown>
      } catch {
        setError("NOVA sent an invalid voice event.")
        return
      }

      const type = payload.type

      if (type === "session.ready") {
        sessionReadyRef.current = true
        authRecoveryAttemptedRef.current = false
        setState("ready")
        setError(null)

        pingTimerRef.current = window.setInterval(() => {
          const activeSocket = socketRef.current
          if (activeSocket?.readyState === WebSocket.OPEN) {
            activeSocket.send(JSON.stringify({ type: "session.ping" }))
          }
        }, 20_000)
        return
      }

      if (type === "turn.started") {
        setState("listening")
        return
      }

      if (type === "speech.started") {
        setState("listening")
        return
      }

      if (type === "transcript.partial") {
        setTranscript(String(payload.text ?? ""))
        setState("listening")
        return
      }

      if (type === "transcript.final") {
        setTranscript(String(payload.text ?? ""))
        setState("thinking")
        return
      }

      if (type === "transcript.utterance_end") {
        setState("thinking")
        deactivateCapture()
        return
      }

      if (type === "turn.committed") {
        deactivateCapture()
        setState("thinking")
        return
      }

      if (type === "assistant.response") {
        setResponse(String(payload.response ?? ""))
        setAudioState((current) =>
          current === "playing" ? current : "preparing",
        )
        setState("speaking")
        return
      }

      if (type === "assistant.audio.started") {
        setAudioState("preparing")
        setState("speaking")
        return
      }

      if (type === "assistant.response.cancelled") {
        clearAutoListenTimer()
        assistantAudioFinalRef.current = false
        stopPlayback()
        setResponse("")
        if (turnIdRef.current === payload.turn_id) {
          deactivateCapture()
        }
        setState((current) =>
          current === "listening" ? current : "ready",
        )
        return
      }

      if (type === "assistant.audio.cancelled") {
        clearAutoListenTimer()
        assistantAudioFinalRef.current = false
        setAudioState("idle")
        stopPlayback()
        setState((current) =>
          current === "listening" ? current : "ready",
        )
        return
      }

      if (type === "assistant.audio.final") {
        await playbackEventChainRef.current
        const serverChunkCount = Number(payload.audio_chunk_count)
        const serverByteCount = Number(payload.audio_byte_count)

        if (Number.isFinite(serverChunkCount)) {
          setAudioChunkCount(serverChunkCount)
        }
        if (Number.isFinite(serverByteCount)) {
          setAudioByteCount(serverByteCount)
        }

        assistantAudioFinalRef.current = true
        if (playbackSourcesRef.current.size === 0) {
          setAudioState("idle")
        }
        scheduleAutoListenRef.current?.()
        return
      }

      if (type === "error") {
        const message = String(payload.message ?? "Voice session error.")
        const code = String(payload.code ?? "voice_error")
        const recoverable = payload.recoverable === true

        if (
          code === "authentication_required" &&
          !authRecoveryAttemptedRef.current
        ) {
          authRecoveryAttemptedRef.current = true
          try {
            await refreshAccessToken()
            if (socketRef.current === socket) {
              socket.close()
            }
            await connect(true)
            return
          } catch {
            setState("disconnected")
            setError("Your NOVA session expired. Please sign in again.")
            return
          }
        }

        clearAutoListenTimer()
        assistantAudioFinalRef.current = false
        setAudioState("idle")
        releaseAudioCapture()

        if (
          recoverable &&
          (code === "assistant_audio_failed" ||
            code === "stt_error" ||
            code === "assistant_execution_failed")
        ) {
          setState("ready")
        } else {
          setState("disconnected")
        }

        setError(message)
      }
    }

    socket.onerror = () => {
      if (socketRef.current === socket && !intentionalCloseRef.current) {
        setError("NOVA voice could not reach the service.")
      }
    }

    socket.onclose = () => {
      if (socketRef.current !== socket) return

      if (pingTimerRef.current !== null) {
        window.clearInterval(pingTimerRef.current)
        pingTimerRef.current = null
      }

      sessionReadyRef.current = false
      releaseAudioCapture()

      if (!intentionalCloseRef.current) {
        setState("disconnected")
        setError((current) => current ?? "NOVA voice disconnected.")
      }
    }
  }, [
    online,
    clearAutoListenTimer,
    ensureAudioOutput,
    releaseAudioCapture,
    stopPlayback,
  ])

  const ensureAudioCapture = useCallback(async () => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      throw new Error("Voice session is not connected.")
    }

    const existingContext = audioContextRef.current
    if (existingContext) {
      if (existingContext.state === "closed") {
        audioContextRef.current = null
        releaseAudioCapture()
      } else {
        await existingContext.resume()
      }
    }

    await ensureAudioOutput()

    if (workletRef.current && micStreamRef.current) {
      return workletRef.current
    }

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: TARGET_CHANNELS,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    })

    const audioContext =
      audioContextRef.current ??
      new AudioContext()

    audioContextRef.current = audioContext
    await audioContext.resume()

    if (workletRef.current) {
      workletRef.current.disconnect()
      workletRef.current = null
    }

    if (workletUrlRef.current === null) {
      const blob = new Blob([PCM_WORKLET_SOURCE], {
        type: "application/javascript",
      })
      workletUrlRef.current = URL.createObjectURL(blob)
    }

    await audioContext.audioWorklet.addModule(workletUrlRef.current)

    const source = audioContext.createMediaStreamSource(stream)
    const worklet = new AudioWorkletNode(audioContext, "nova-pcm-processor")
    const muteGain = audioContext.createGain()
    muteGain.gain.value = 0

    worklet.port.onmessage = (event) => {
      const socketNow = socketRef.current
      const turnId = turnIdRef.current

      if (
        !turnId ||
        !socketNow ||
        socketNow.readyState !== WebSocket.OPEN ||
        !(event.data instanceof ArrayBuffer)
      ) {
        return
      }

      socketNow.send(event.data)
    }

    source.connect(worklet)
    worklet.connect(muteGain)
    muteGain.connect(audioContext.destination)

    micStreamRef.current = stream
    micSourceRef.current = source
    workletRef.current = worklet
    muteGainRef.current = muteGain

    return worklet
  }, [ensureAudioOutput, releaseAudioCapture])

  const startTurn = useCallback(async () => {
    if (!sessionReadyRef.current) {
      setError("Voice is still connecting. Try again in a moment.")
      return
    }

    clearAutoListenTimer()
    assistantAudioFinalRef.current = false
    setAudioChunkCount(0)
    setAudioByteCount(0)
    stopPlayback()
    setResponse("")
    setTranscript("")
    setError(null)

    try {
      const worklet = await ensureAudioCapture()
      const socket = socketRef.current
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        throw new Error("Voice session disconnected.")
      }

      const turnId = requestId()
      turnIdRef.current = turnId

      socket.send(
        JSON.stringify({
          type: "turn.start",
          turn_id: turnId,
          audio_format: {
            encoding: TARGET_ENCODING,
            sample_rate_hz: TARGET_SAMPLE_RATE,
            channels: TARGET_CHANNELS,
          },
        }),
      )

      worklet.port.postMessage({ type: "set-active", active: true })
      setState("listening")
    } catch (err) {
      deactivateCapture()
      setState("ready")
      setError(
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "Microphone access was blocked. Allow microphone access and try again."
          : formatError(err, "NOVA could not access the microphone."),
      )
    }
  }, [
    ensureAudioCapture,
    clearAutoListenTimer,
    deactivateCapture,
    stopPlayback,
  ])

  useEffect(() => {
    startTurnRef.current = startTurn
    return () => {
      startTurnRef.current = null
    }
  }, [startTurn])

  const scheduleAutoListen = useCallback(() => {
    clearAutoListenTimer()

    if (
      !assistantAudioFinalRef.current ||
      !sessionReadyRef.current ||
      intentionalCloseRef.current ||
      turnIdRef.current !== null
    ) {
      return
    }

    const audioContext = audioContextRef.current
    const remainingMilliseconds = audioContext
      ? Math.max(
          0,
          (playbackEndTimeRef.current - audioContext.currentTime) * 1000,
        )
      : 0

    autoListenTimerRef.current = window.setTimeout(() => {
      autoListenTimerRef.current = null

      if (
        !assistantAudioFinalRef.current ||
        !sessionReadyRef.current ||
        intentionalCloseRef.current ||
        turnIdRef.current !== null
      ) {
        return
      }

      assistantAudioFinalRef.current = false
      void startTurnRef.current?.()
    }, remainingMilliseconds + 80)
  }, [clearAutoListenTimer])

  useEffect(() => {
    scheduleAutoListenRef.current = scheduleAutoListen
    return () => {
      scheduleAutoListenRef.current = null
    }
  }, [scheduleAutoListen])

  const commitTurn = useCallback(() => {
    const socket = socketRef.current
    const turnId = turnIdRef.current

    if (!turnId || !socket || socket.readyState !== WebSocket.OPEN) return

    socket.send(
      JSON.stringify({
        type: "turn.commit",
        turn_id: turnId,
      }),
    )

    deactivateCapture()
    setState("thinking")
  }, [deactivateCapture])

  useEffect(() => {
    const handleOnline = () => setOnline(true)
    const handleOffline = () => setOnline(false)

    window.addEventListener("online", handleOnline)
    window.addEventListener("offline", handleOffline)

    return () => {
      window.removeEventListener("online", handleOnline)
      window.removeEventListener("offline", handleOffline)
    }
  }, [])

  useEffect(() => {
    if (!online) {
      setState("disconnected")
      setError("You are offline. Reconnect when your connection is restored.")
      return
    }

    void connect()

    return () => {
      clearAutoListenTimer()
      closeSocket()

      if (audioContextRef.current) {
        void audioContextRef.current.close()
        audioContextRef.current = null
      }

      if (workletUrlRef.current) {
        URL.revokeObjectURL(workletUrlRef.current)
        workletUrlRef.current = null
      }
    }
  }, [online, connect, closeSocket, clearAutoListenTimer])

  const handleVoiceButton = () => {
    if (state === "listening") {
      commitTurn()
      return
    }

    if (state === "thinking" || state === "speaking") {
      void startTurn()
      return
    }

    void startTurn()
  }

  const statusCopy: Record<VoiceState, string> = {
    connecting: "Connecting",
    ready: "Ready",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
    reconnecting: "Reconnecting",
    disconnected: "Disconnected",
  }

  const buttonCopy: Record<VoiceState, string> = {
    connecting: "Connecting…",
    ready: "Talk to NOVA",
    listening: "Send now",
    thinking: "Interrupt & talk",
    speaking: "Interrupt & talk",
    reconnecting: "Reconnecting…",
    disconnected: "Reconnect",
  }

  const audioLabel =
    audioState === "playing"
      ? "AUDIO LIVE"
      : audioState === "preparing"
        ? "PREPARING AUDIO"
        : null

  const voiceButtonDisabled =
    state === "connecting" ||
    state === "reconnecting" ||
    (!online && state !== "disconnected")

  return (
    <div className="voice-shell">
      <header className="voice-header">
        <div>
          <div className="section-kicker">REAL-TIME VOICE</div>
          <h1>Talk with NOVA</h1>
        </div>

        <div className={online && state !== "disconnected" ? "voice-status online" : "voice-status"}>
          <span className="connection-dot" />
          <span>{statusCopy[state]}</span>
        </div>
      </header>

      <main className="voice-main">
        <section className="voice-stage" aria-label="NOVA voice session">
          <div className={`voice-orb voice-orb-${state}`}>
            <div className="voice-orb-ring voice-orb-ring-one" />
            <div className="voice-orb-ring voice-orb-ring-two" />
            <div className="voice-orb-core">
              <Icon name="mic" size={31} />
            </div>
          </div>

          <div className="voice-stage-copy" aria-live="polite">
            <div className="section-kicker">{statusCopy[state]}</div>
            <h2>
              {state === "listening"
                ? "I’m listening."
                : state === "thinking"
                  ? "Let me think."
                  : state === "speaking"
                    ? "I’m speaking."
                    : state === "disconnected"
                      ? "Voice is offline."
                      : "Speak naturally."}
            </h2>
            <p>
              {state === "listening"
                ? "Speak naturally. NOVA detects when your turn ends automatically."
                : state === "thinking"
                  ? "NOVA is processing your request. You can interrupt at any time."
                  : state === "speaking"
                    ? audioState === "playing"
                      ? "NOVA is speaking aloud. You can interrupt at any time."
                      : "NOVA is preparing the voice response. You can interrupt at any time."
                  : "Your voice session stays private to this signed-in NOVA account."}
            </p>
          </div>

          {transcript && (
            <div className="voice-turn-card user">
              <div className="voice-turn-label">YOU</div>
              <p>{transcript}</p>
            </div>
          )}

          {response && (
            <div className="voice-turn-card assistant">
              <div className="voice-turn-label">
                <span>NOVA</span>
                {audioLabel && <span className={`voice-audio-label ${audioState}`}>{audioLabel}</span>}
              </div>
              {audioState !== "idle" && (
                <div className={`voice-audio-status ${audioState}`} role="status" aria-live="polite">
                  <span className="voice-audio-bars" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                  </span>
                  <span>
                    {audioState === "playing"
                      ? "NOVA is speaking"
                      : "Voice response is loading"}
                  </span>
                  {audioChunkCount === 0 && audioState !== "idle" && (
                    <small className="voice-audio-debug">
                      No audio chunks received yet
                    </small>
                  )}
                </div>
              )}
              <p>{response}</p>
              {audioState !== "idle" && (
                <small className="voice-audio-debug">
                  Audio stream: {audioChunkCount} chunks · {audioByteCount} bytes
                </small>
              )}
            </div>
          )}

          {error && (
            <div className="voice-error" role="alert">
              <span>{error}</span>
              {state === "disconnected" && online && (
                <button type="button" onClick={() => void connect(true)}>
                  Reconnect
                </button>
              )}
            </div>
          )}

          <button
            className={state === "listening" ? "voice-primary-action active" : "voice-primary-action"}
            type="button"
            onClick={state === "disconnected" ? () => void connect(true) : handleVoiceButton}
            disabled={voiceButtonDisabled}
            aria-label={buttonCopy[state]}
          >
            <Icon name="mic" size={19} />
            {buttonCopy[state]}
          </button>

          <button
            className="voice-history-action"
            type="button"
            onClick={onOpenConversation}
          >
            View conversation history
          </button>
        </section>
      </main>
    </div>
  )
}
