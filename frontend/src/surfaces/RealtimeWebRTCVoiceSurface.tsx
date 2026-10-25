import { useCallback, useEffect, useRef, useState } from "react"

import {
  ApiRequestError,
  apiRequestWithRefresh,
  getAccessToken,
  refreshAccessToken,
} from "../api/client"
import { buildApiUrl } from "../app/config"
import {
  getVoiceLanguagePreference,
  setVoiceLanguagePreference,
  type VoiceLanguage,
} from "../app/voiceLanguage"
import { VoiceTransportControl, type VoiceTransport } from "./VoiceTransportControl"
import { Icon } from "../components/Icon"

type VoiceState =
  | "connecting"
  | "ready"
  | "listening"
  | "thinking"
  | "speaking"
  | "reconnecting"
  | "disconnected"

type MicrophonePermission = "unknown" | "prompt" | "granted" | "denied"

type ConversationCreated = { id: number }
type ChatToolResult = Record<string, unknown>
type RealtimeEvent = Record<string, unknown>
type FunctionCallItem = {
  type?: string
  name?: string
  call_id?: string
  arguments?: string
}

type ActiveVoiceTurn = {
  userText: string
  assistantText: string
  responseDone: boolean
  toolUsed: boolean
  saveStarted: boolean
  cancelled: boolean
}

function emptyTurn(): ActiveVoiceTurn {
  return {
    userText: "",
    assistantText: "",
    responseDone: false,
    toolUsed: false,
    saveStarted: false,
    cancelled: false,
  }
}

function readableError(error: unknown, fallback: string): string {
  if (error instanceof ApiRequestError) return error.detail
  if (error instanceof Error && error.message) return error.message
  return fallback
}

function emitEvent(channel: RTCDataChannel | null, event: RealtimeEvent): void {
  if (channel?.readyState !== "open") return
  channel.send(JSON.stringify(event))
}

function boundedToolOutput(result: ChatToolResult): string {
  const summary: Record<string, unknown> = {}
  for (const field of [
    "response",
    "error",
    "understanding",
    "plan",
    "permission",
    "confirmation",
    "tool_result",
    "workflow_result",
    "web_sources",
    "knowledge_sources",
  ]) {
    if (field in result) summary[field] = result[field]
  }
  const serialized = JSON.stringify(summary)
  return serialized.length <= 14000 ? serialized : serialized.slice(0, 14000)
}

async function postWebRtcOffer(
  sdp: string,
  conversationId: number,
  language: VoiceLanguage,
): Promise<string> {
  const url = buildApiUrl("/voice/realtime/session")
    + "?conversation_id=" + encodeURIComponent(String(conversationId))
    + "&language=" + encodeURIComponent(language)

  for (let attempt = 0; attempt < 2; attempt += 1) {
    let token = getAccessToken()
    if (!token) {
      try {
        token = (await refreshAccessToken()).access_token
      } catch {
        throw new Error("Your NOVA session expired. Please sign in again.")
      }
    }

    let response: Response
    try {
      response = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/sdp",
          Accept: "application/sdp",
        },
        body: sdp,
      })
    } catch {
      throw new Error("NOVA could not reach the realtime voice service.")
    }

    if (response.status === 401 && attempt === 0) {
      try {
        await refreshAccessToken()
        continue
      } catch {
        throw new Error("Your NOVA session expired. Please sign in again.")
      }
    }

    if (!response.ok) {
      let detail = "NOVA could not establish realtime voice."
      try {
        const payload = (await response.json()) as { detail?: unknown }
        if (typeof payload.detail === "string") detail = payload.detail
      } catch {
        // The SDP endpoint can return plain text errors from middleware.
      }
      throw new Error(detail)
    }

    const answer = await response.text()
    if (!answer.trim().startsWith("v=")) {
      throw new Error("NOVA received an invalid WebRTC session answer.")
    }
    return answer
  }

  throw new Error("NOVA could not authenticate the realtime voice session.")
}

export function RealtimeWebRTCVoiceSurface({
  onOpenConversation,
  voiceTransport,
  onVoiceTransportChange,
}: {
  onOpenConversation: () => void
  voiceTransport: VoiceTransport
  onVoiceTransportChange: (value: VoiceTransport) => void
}) {
  const [state, setState] = useState<VoiceState>("ready")
  const stateRef = useRef<VoiceState>("ready")
  stateRef.current = state
  const [connected, setConnected] = useState(false)
  const [transcript, setTranscript] = useState("")
  const [response, setResponse] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [audioState, setAudioState] = useState<"idle" | "preparing" | "playing">("idle")
  const [microphonePermission, setMicrophonePermission] =
    useState<MicrophonePermission>("unknown")
  const [voiceLanguage, setVoiceLanguage] = useState<VoiceLanguage>(
    () => getVoiceLanguagePreference(),
  )
  const [languageSettingsOpen, setLanguageSettingsOpen] = useState(false)

  const peerRef = useRef<RTCPeerConnection | null>(null)
  const channelRef = useRef<RTCDataChannel | null>(null)
  const microphoneRef = useRef<MediaStream | null>(null)
  const remoteAudioRef = useRef<HTMLAudioElement | null>(null)
  const conversationIdRef = useRef<number | null>(null)
  const connectingRef = useRef(false)
  const connectedRef = useRef(false)
  const intentionalCloseRef = useRef(false)
  const userIsSpeakingRef = useRef(false)
  const handledToolCallsRef = useRef<Set<string>>(new Set())
  const activeTurnRef = useRef<ActiveVoiceTurn>(emptyTurn())
  const connectTimeoutRef = useRef<number | null>(null)
  const voiceLanguageRef = useRef(voiceLanguage)
  voiceLanguageRef.current = voiceLanguage

  const clearConnectTimeout = useCallback(() => {
    if (connectTimeoutRef.current !== null) {
      window.clearTimeout(connectTimeoutRef.current)
      connectTimeoutRef.current = null
    }
  }, [])

  const releaseConnection = useCallback(() => {
    clearConnectTimeout()

    const channel = channelRef.current
    channelRef.current = null
    if (channel && channel.readyState !== "closed") {
      try {
        channel.close()
      } catch {
        // Continue releasing the peer and microphone.
      }
    }

    const peer = peerRef.current
    peerRef.current = null
    if (peer && peer.connectionState !== "closed") {
      try {
        peer.close()
      } catch {
        // Continue releasing the microphone.
      }
    }

    const stream = microphoneRef.current
    microphoneRef.current = null
    stream?.getTracks().forEach((track) => track.stop())

    if (remoteAudioRef.current) {
      remoteAudioRef.current.pause()
      remoteAudioRef.current.srcObject = null
    }

    connectedRef.current = false
    connectingRef.current = false
    userIsSpeakingRef.current = false
    setConnected(false)
    setAudioState("idle")
  }, [clearConnectTimeout])

  const persistTurnWhenReady = useCallback(() => {
    const turn = activeTurnRef.current
    if (
      !turn.responseDone ||
      turn.cancelled ||
      turn.toolUsed ||
      turn.saveStarted ||
      !turn.userText.trim() ||
      !turn.assistantText.trim()
    ) {
      return
    }

    const conversationId = conversationIdRef.current
    if (!conversationId) return

    turn.saveStarted = true
    void apiRequestWithRefresh<{ saved: boolean; conversation_id: number }>(
      "/voice/realtime/turns",
      {
        method: "POST",
        body: JSON.stringify({
          conversation_id: conversationId,
          user_text: turn.userText,
          assistant_text: turn.assistantText,
        }),
      },
    )
      .then((saved) => {
        conversationIdRef.current = saved.conversation_id
      })
      .catch(() => {
        setError("This voice turn could not be saved to conversation history.")
      })
  }, [])

  const executeToolCall = useCallback(async (
    item: FunctionCallItem,
    channel: RTCDataChannel,
  ) => {
    const callId = typeof item.call_id === "string" ? item.call_id : ""
    if (!callId || handledToolCallsRef.current.has(callId)) return
    handledToolCallsRef.current.add(callId)

    const activeTurn = activeTurnRef.current
    activeTurn.toolUsed = true
    setAudioState("preparing")
    setState("thinking")

    let toolOutput: string
    try {
      const parsed = JSON.parse(item.arguments || "{}") as { request?: unknown }
      const requestText = typeof parsed.request === "string" ? parsed.request.trim() : ""
      if (!requestText) {
        toolOutput = JSON.stringify({
          error: "The NOVA request was empty. Ask the user to repeat it.",
          action_taken: false,
        })
      } else {
        const conversationId = conversationIdRef.current
        if (!conversationId) {
          throw new Error("The NOVA conversation is not ready.")
        }
        const result = await apiRequestWithRefresh<ChatToolResult>("/chat", {
          method: "POST",
          headers: { "Idempotency-Key": callId },
          body: JSON.stringify({
            message: requestText,
            conversation_id: conversationId,
          }),
        })
        toolOutput = boundedToolOutput(result)
      }
    } catch (toolError) {
      toolOutput = JSON.stringify({
        error: readableError(toolError, "NOVA could not complete the request."),
        action_taken: false,
      })
    }

    emitEvent(channel, {
      type: "conversation.item.create",
      item: {
        type: "function_call_output",
        call_id: callId,
        output: toolOutput,
      },
    })

    if (!userIsSpeakingRef.current && channel.readyState === "open") {
      emitEvent(channel, { type: "response.create" })
    } else {
      activeTurn.cancelled = true
    }
  }, [])

  const handleRealtimeEvent = useCallback((event: RealtimeEvent, channel: RTCDataChannel) => {
    const type = typeof event.type === "string" ? event.type : ""

    if (type === "session.created" || type === "session.updated") {
      setError(null)
      return
    }

    if (type === "input_audio_buffer.speech_started") {
      if (
        stateRef.current === "speaking" ||
        stateRef.current === "thinking" ||
        activeTurnRef.current.responseDone ||
        activeTurnRef.current.saveStarted ||
        activeTurnRef.current.toolUsed ||
        activeTurnRef.current.cancelled ||
        activeTurnRef.current.assistantText.trim()
      ) {
        activeTurnRef.current = emptyTurn()
      }
      userIsSpeakingRef.current = true
      setTranscript("")
      setResponse("")
      setAudioState("idle")
      setState("listening")
      return
    }

    if (type === "input_audio_buffer.speech_stopped") {
      userIsSpeakingRef.current = false
      setState((current) => current === "speaking" ? current : "thinking")
      return
    }

    if (type === "conversation.item.input_audio_transcription.completed") {
      const transcriptText = typeof event.transcript === "string"
        ? event.transcript.trim()
        : ""
      if (transcriptText) {
        const activeTurn = activeTurnRef.current
        activeTurn.userText = transcriptText
        setTranscript(transcriptText)
      }
      return
    }

    if (type === "response.created") {
      setState("thinking")
      setAudioState((current) => current === "playing" ? current : "preparing")
      return
    }

    if (type === "output_audio_buffer.started") {
      setState("speaking")
      setAudioState("playing")
      return
    }

    if (type === "response.output_audio_transcript.delta") {
      const delta = typeof event.delta === "string" ? event.delta : ""
      if (delta) {
        activeTurnRef.current.assistantText += delta
        setResponse(activeTurnRef.current.assistantText)
      }
      return
    }

    if (type === "response.output_audio_transcript.done") {
      const finalTranscript = typeof event.transcript === "string"
        ? event.transcript.trim()
        : ""
      if (finalTranscript) {
        activeTurnRef.current.assistantText = finalTranscript
        setResponse(finalTranscript)
      }
      persistTurnWhenReady()
      return
    }

    if (type === "response.output_item.done") {
      const item = (event.item && typeof event.item === "object")
        ? event.item as FunctionCallItem
        : null
      if (item?.type === "function_call" && item.name === "nova_execute_request") {
        void executeToolCall(item, channel)
      }
      return
    }

    if (type === "response.done") {
      const responseData = (event.response && typeof event.response === "object")
        ? event.response as Record<string, unknown>
        : {}
      const statusValue = typeof responseData.status === "string"
        ? responseData.status
        : "completed"
      const activeTurn = activeTurnRef.current
      activeTurn.responseDone = true
      if (statusValue !== "completed") activeTurn.cancelled = true
      persistTurnWhenReady()

      if (statusValue !== "completed") {
        setAudioState("idle")
        if (!userIsSpeakingRef.current) setState("ready")
      }
      return
    }

    if (type === "output_audio_buffer.stopped") {
      setAudioState("idle")
      if (!userIsSpeakingRef.current) setState("ready")
      persistTurnWhenReady()
      return
    }

    if (type === "error") {
      const payload = (event.error && typeof event.error === "object")
        ? event.error as Record<string, unknown>
        : {}
      const code = typeof payload.code === "string" ? payload.code : ""
      const message = code === "insufficient_quota"
        ? "Realtime voice quota or billing is unavailable for the configured API account."
        : "Realtime voice reported an error. Please try again."
      setError(message)
      setAudioState("idle")
      if (code === "invalid_api_key" || code === "session_expired") {
        setState("disconnected")
        releaseConnection()
      } else if (!userIsSpeakingRef.current) {
        setState("ready")
      }
      return
    }
  }, [executeToolCall, persistTurnWhenReady, releaseConnection])

  const connect = useCallback(async () => {
    if (connectingRef.current || connectedRef.current) return
    if (!navigator.mediaDevices?.getUserMedia || typeof RTCPeerConnection === "undefined") {
      setState("disconnected")
      setError("This browser does not support realtime WebRTC voice.")
      return
    }

    connectingRef.current = true
    intentionalCloseRef.current = false
    setState("connecting")
    setError(null)
    setAudioState("preparing")

    let stream: MediaStream | null = null
    let peer: RTCPeerConnection | null = null

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: { ideal: "all" },
          noiseSuppression: true,
          autoGainControl: false,
        },
      })
      microphoneRef.current = stream
      setMicrophonePermission("granted")

      if (!conversationIdRef.current) {
        const conversation = await apiRequestWithRefresh<ConversationCreated>(
          "/conversations",
          {
            method: "POST",
            body: JSON.stringify({ title: "NOVA Voice Conversation" }),
          },
        )
        conversationIdRef.current = conversation.id
      }

      peer = new RTCPeerConnection()
      peerRef.current = peer
      stream.getAudioTracks().forEach((track) => peer?.addTrack(track, stream as MediaStream))

      peer.ontrack = (event) => {
        const audioElement = remoteAudioRef.current
        if (!audioElement) return
        audioElement.srcObject = event.streams[0]
        void audioElement.play().catch(() => {
          setError("Browser audio is blocked. Click the voice orb once to enable playback.")
        })
      }

      peer.onconnectionstatechange = () => {
        if (intentionalCloseRef.current || peerRef.current !== peer) return
        if (peer?.connectionState === "failed") {
          setState("disconnected")
          setError("Realtime voice connection failed. Tap to reconnect.")
          releaseConnection()
        } else if (peer?.connectionState === "disconnected") {
          setError("Realtime voice connection was interrupted.")
        }
      }

      const channel = peer.createDataChannel("oai-events")
      channelRef.current = channel
      channel.onopen = () => {
        if (channelRef.current !== channel) return
        clearConnectTimeout()
        connectingRef.current = false
        connectedRef.current = true
        setConnected(true)
        setState("ready")
        setAudioState("idle")
        setError(null)
      }
      channel.onmessage = (message) => {
        if (channelRef.current !== channel || typeof message.data !== "string") return
        try {
          const event = JSON.parse(message.data) as RealtimeEvent
          handleRealtimeEvent(event, channel)
        } catch {
          setError("NOVA received an unreadable realtime voice event.")
        }
      }
      channel.onerror = () => {
        if (channelRef.current === channel) {
          setError("Realtime voice event channel encountered a network error.")
        }
      }
      channel.onclose = () => {
        if (intentionalCloseRef.current || channelRef.current !== channel) return
        connectedRef.current = false
        setConnected(false)
        setState("disconnected")
      }

      const offer = await peer.createOffer()
      await peer.setLocalDescription(offer)
      const sdp = offer.sdp || peer.localDescription?.sdp
      if (!sdp) throw new Error("Browser could not create the WebRTC offer.")

      const answerSdp = await postWebRtcOffer(
        sdp,
        conversationIdRef.current,
        voiceLanguageRef.current,
      )
      await peer.setRemoteDescription({ type: "answer", sdp: answerSdp })

      clearConnectTimeout()
      connectTimeoutRef.current = window.setTimeout(() => {
        if (connectedRef.current || intentionalCloseRef.current) return
        setError("Realtime voice took too long to connect. Tap to retry.")
        setState("disconnected")
        releaseConnection()
      }, 22000)
    } catch (connectError) {
      const mediaError = connectError instanceof DOMException
        && (connectError.name === "NotAllowedError" || connectError.name === "PermissionDeniedError")
      if (mediaError) setMicrophonePermission("denied")
      setError(readableError(
        connectError,
        "NOVA could not start realtime voice. Check microphone permission and try again.",
      ))
      intentionalCloseRef.current = true
      releaseConnection()
      setState("disconnected")
    } finally {
      connectingRef.current = false
    }
  }, [clearConnectTimeout, handleRealtimeEvent, releaseConnection])

  const stopSession = useCallback(() => {
    intentionalCloseRef.current = true
    releaseConnection()
    setError(null)
    setState("ready")
  }, [releaseConnection])

  const interruptResponse = useCallback(() => {
    const channel = channelRef.current
    emitEvent(channel, { type: "response.cancel" })
    emitEvent(channel, { type: "output_audio_buffer.clear" })
    activeTurnRef.current.cancelled = true
    setAudioState("idle")
    setState(connectedRef.current ? "ready" : "disconnected")
  }, [])

  useEffect(() => {
    const updateOnline = () => {
      if (!navigator.onLine) {
        setError("Internet connection is unavailable.")
      } else {
        setError(null)
      }
    }
    window.addEventListener("online", updateOnline)
    window.addEventListener("offline", updateOnline)
    return () => {
      window.removeEventListener("online", updateOnline)
      window.removeEventListener("offline", updateOnline)
      intentionalCloseRef.current = true
      releaseConnection()
    }
  }, [releaseConnection])

  const changeLanguage = (value: VoiceLanguage) => {
    setVoiceLanguage(value)
    setVoiceLanguagePreference(value)
    if (connectedRef.current) {
      setError("Language preference will apply to the next realtime session. Pause voice and reconnect to apply it.")
    }
  }

  const handleVoiceButton = () => {
    if (state === "thinking" || state === "speaking") {
      interruptResponse()
      return
    }
    if (connectedRef.current) {
      stopSession()
      return
    }
    void connect()
  }

  const statusLabel = state === "ready" && !connected
    ? "VOICE STANDBY"
    : state === "ready"
      ? "READY TO LISTEN"
      : state.toUpperCase().replaceAll("_", " ")

  const buttonLabel = state === "connecting"
    ? "Connecting…"
    : state === "disconnected"
      ? "Reconnect voice"
      : state === "thinking" || state === "speaking"
        ? "Interrupt & talk"
        : connected
          ? state === "listening" ? "Pause listening" : "Pause voice"
          : "Talk to NOVA"

  return (
    <div className="voice-shell">
      <header className="voice-header">
        <button
          className="voice-icon-action voice-exit-action"
          type="button"
          onClick={() => {
            stopSession()
            onOpenConversation()
          }}
          aria-label="Back to conversation"
          title="Back to conversation"
        >
          <Icon name="close" size={18} />
        </button>

        <div className="voice-brand-state" aria-live="polite">
          <div className="voice-brand-label">NOVA · AI VOICE ASSISTANT</div>
          <div className={"voice-live-state " + state}>
            {statusLabel}
          </div>
        </div>

        <button
          className={languageSettingsOpen
            ? "voice-icon-action voice-settings-action active"
            : "voice-icon-action voice-settings-action"}
          type="button"
          onClick={() => setLanguageSettingsOpen((open) => !open)}
          aria-label="Voice language settings"
          aria-expanded={languageSettingsOpen}
          title="Voice language"
        >
          <Icon name="sliders" size={18} />
        </button>
      </header>

      <main className="voice-main">
        <section className="voice-stage" aria-label="NOVA realtime voice session">
          <button
            className={"voice-orb voice-orb-" + state}
            type="button"
            onClick={state === "disconnected" ? () => void connect() : handleVoiceButton}
            disabled={state === "connecting" || state === "reconnecting"}
            aria-label={buttonLabel}
            aria-pressed={connected}
            title={buttonLabel}
          >
            <span className="voice-orb-aura" aria-hidden="true" />
            <span className="voice-orb-gradient-ring" aria-hidden="true" />
            <span className="voice-orb-sphere" aria-hidden="true">
              <span className="voice-orb-sheen" />
              <span className="voice-orb-wave wave-one" />
              <span className="voice-orb-wave wave-two" />
              <span className="voice-orb-wave wave-three" />
              <span className="voice-orb-wave wave-four" />
            </span>
            <span className="voice-orb-sr-label">{buttonLabel}</span>
          </button>

          <audio ref={remoteAudioRef} autoPlay playsInline aria-label="NOVA voice output" style={{ display: "none" }} />

          <div className="voice-accessible-transcript" aria-label="Voice transcript" aria-live="polite">
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
                  {audioState !== "idle" && (
                    <span className={"voice-audio-label " + audioState}>
                      {audioState === "playing" ? "AUDIO LIVE" : "PREPARING AUDIO"}
                    </span>
                  )}
                </div>
                {audioState !== "idle" && (
                  <div className={"voice-audio-status " + audioState} role="status" aria-live="polite">
                    <span className="voice-audio-bars" aria-hidden="true">
                      <i /><i /><i /><i /><i />
                    </span>
                    <span>
                      {audioState === "playing"
                        ? "NOVA is speaking"
                        : "Preparing realtime response"}
                    </span>
                  </div>
                )}
                <p>{response}</p>
              </div>
            )}
          </div>

          {error && (
            <div className="voice-error" role="alert">
              <span>{error}</span>
              {(state === "disconnected" || connected) && (
                <button
                  type="button"
                  onClick={() => {
                    if (connected) stopSession()
                    else void connect()
                  }}
                >
                  {connected ? "Pause" : "Reconnect"}
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  const legacyUrl = new URL(window.location.href)
                  legacyUrl.searchParams.set("voice_transport", "legacy")
                  window.location.assign(legacyUrl.toString())
                }}
              >
                Use classic voice
              </button>
            </div>
          )}

          {microphonePermission === "denied" && (
            <small className="voice-microphone-state voice-microphone-warning" role="status">
              Microphone access is blocked in browser settings.
            </small>
          )}

          {languageSettingsOpen && (
            <div className="voice-language-control voice-language-popover">
              <VoiceTransportControl
                value={voiceTransport}
                onChange={onVoiceTransportChange}
              />
              <label htmlFor="nova-voice-language">Speech language</label>
              <select
                id="nova-voice-language"
                value={voiceLanguage}
                onChange={(event) => changeLanguage(event.target.value as VoiceLanguage)}
              >
                <option value="multi">Automatic (mirror speaker)</option>
                <option value="en-US">English</option>
                <option value="ur">Urdu (Pakistan)</option>
                <option value="hi">Hindi</option>
              </select>
              <p>Automatic mode mirrors English, Urdu, Roman Urdu/Hinglish, or Hindi.</p>
              <button
                type="button"
                className="voice-language-close"
                onClick={() => setLanguageSettingsOpen(false)}
              >
                Done
              </button>
            </div>
          )}
        </section>

        <footer className="voice-footer">
          <span>
            {connected
              ? "Realtime audio · hands-free turn taking"
              : "Start voice to enable your microphone"}
          </span>
          <span className="voice-footer-divider" aria-hidden="true">·</span>
          <span>{connected ? "Speak naturally; interrupt any time" : "WebRTC speech-to-speech"}</span>
        </footer>
      </main>
    </div>
  )
}
