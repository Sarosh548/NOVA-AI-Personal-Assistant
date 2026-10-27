import { useCallback, useEffect, useRef, useState } from "react"

import {
  ApiRequestError,
  apiRequestWithRefresh,
} from "../api/client"
import { Icon } from "../components/Icon"
import {
  getVoiceLanguagePreference,
  setVoiceLanguagePreference,
  type VoiceLanguage,
} from "../app/voiceLanguage"
import { VoiceTransportControl, type VoiceTransport } from "./VoiceTransportControl"

type VoiceState = "connecting" | "ready" | "listening" | "thinking" | "speaking" | "disconnected"
type GeminiTokenResponse = {
  token: string
  model: string
  config: Record<string, unknown>
  expires_at: string
}
type ConversationCreated = { id: number }
type ToolResult = Record<string, unknown>
type VoiceSearchSource = {
  title: string
  url: string
  snippet: string
  publishedDate: string | null
  host: string
}
type VoiceTranscriptTurn = {
  id: number
  userText: string
  assistantText: string
  searchStatus: string | null
  searchSources: VoiceSearchSource[]
}
type ActiveTurn = VoiceTranscriptTurn & {
  responseDone: boolean
  toolUsed: boolean
  saveStarted: boolean
  cancelled: boolean
}
type GeminiMessage = Record<string, any>

const INPUT_RATE = 16000
const OUTPUT_RATE = 24000
const MAX_AUTOMATIC_RECONNECT_ATTEMPTS = 2
const AUTOMATIC_RECONNECT_DELAYS_MS = [1_000, 2_500] as const
const CONNECTION_STABILITY_WINDOW_MS = 30_000

const PCM_WORKLET_SOURCE = [
  "class NovaGeminiPcmProcessor extends AudioWorkletProcessor {",
  "  constructor() {",
  "    super()",
  "    this.active = true",
  "    this.buffer = new Float32Array(0)",
  "    this.position = 0",
  "    this.targetRate = 16000",
  "    this.chunkSize = 1600",
  "    this.noiseFloor = 0.003",
  "    this.activationSamples = 0",
  "    this.speechSamples = 0",
  "    this.silenceSamples = 0",
  "    this.vadTriggered = false",
  "    this.port.onmessage = (event) => {",
  "      if (event.data && event.data.type === 'set-active') {",
  "        this.active = Boolean(event.data.active)",
  "        if (!this.active) {",
  "          this.buffer = new Float32Array(0)",
  "          this.position = 0",
  "          this.activationSamples = 0",
  "          this.speechSamples = 0",
  "          this.silenceSamples = 0",
  "          this.vadTriggered = false",
  "        }",
  "      }",
  "    }",
  "  }",
  "  process(inputs) {",
  "    const channel = inputs[0] && inputs[0][0]",
  "    if (!channel || !this.active) return true",
  "    let energy = 0",
  "    for (let i = 0; i < channel.length; i += 1) energy += channel[i] * channel[i]",
  "    const rms = Math.sqrt(energy / Math.max(1, channel.length))",
  "    this.noiseFloor = this.noiseFloor * 0.995 + rms * 0.005",
  "    const threshold = Math.max(0.012, this.noiseFloor * 2.5)",
  "    this.activationSamples += channel.length",
  "    if (this.activationSamples >= sampleRate * 0.1 && rms >= threshold) {",
  "      this.speechSamples += channel.length",
  "      this.silenceSamples = 0",
  "      if (!this.vadTriggered && this.speechSamples >= sampleRate * 0.12) {",
  "        this.vadTriggered = true",
  "        this.port.postMessage({ type: 'voice-start' })",
  "      }",
  "    } else {",
  "      this.speechSamples = Math.max(0, this.speechSamples - channel.length)",
  "      this.silenceSamples += channel.length",
  "      if (this.silenceSamples >= sampleRate * 0.45) {",
  "        this.vadTriggered = false",
  "        this.speechSamples = 0",
  "      }",
  "    }",
  "    const merged = new Float32Array(this.buffer.length + channel.length)",
  "    merged.set(this.buffer)",
  "    merged.set(channel, this.buffer.length)",
  "    this.buffer = merged",
  "    const step = sampleRate / this.targetRate",
  "    while (this.position + (this.chunkSize - 1) * step < this.buffer.length) {",
  "      const pcm = new Int16Array(this.chunkSize)",
  "      for (let i = 0; i < this.chunkSize; i += 1) {",
  "        const pos = this.position + i * step",
  "        const leftIndex = Math.floor(pos)",
  "        const fraction = pos - leftIndex",
  "        const left = this.buffer[leftIndex] || 0",
  "        const right = this.buffer[leftIndex + 1] ?? left",
  "        const sample = Math.max(-1, Math.min(1, left + (right - left) * fraction))",
  "        pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff",
  "      }",
  "      this.position += this.chunkSize * step",
  "      const consumed = Math.floor(this.position)",
  "      if (consumed > 0) {",
  "        this.buffer = this.buffer.slice(consumed)",
  "        this.position -= consumed",
  "      }",
  "      this.port.postMessage(pcm.buffer, [pcm.buffer])",
  "    }",
  "    return true",
  "  }",
  "}",
  "registerProcessor('nova-gemini-pcm-processor', NovaGeminiPcmProcessor)",
].join("\n")

let voiceTurnSequence = 0

function newTurn(): ActiveTurn {
  return {
    id: ++voiceTurnSequence,
    userText: "",
    assistantText: "",
    searchStatus: null,
    searchSources: [],
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

function appendTranscript(current: string, incoming: string): string {
  const next = incoming.trim()
  const previous = current.trim()
  if (!next) return previous
  if (!previous) return next
  if (next === previous || previous.endsWith(next)) return previous
  if (next.startsWith(previous)) return next

  const overlapLimit = Math.min(previous.length, next.length, 120)
  for (let length = overlapLimit; length >= 8; length -= 1) {
    if (previous.slice(-length).toLowerCase() === next.slice(0, length).toLowerCase()) {
      return (previous + next.slice(length)).trim()
    }
  }
  return (previous + " " + next).trim()
}

function bytesToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ""
  const chunkSize = 0x8000
  for (let start = 0; start < bytes.length; start += chunkSize) {
    const slice = bytes.subarray(start, Math.min(bytes.length, start + chunkSize))
    binary += String.fromCharCode(...slice)
  }
  return window.btoa(binary)
}

function base64PcmToAudioBuffer(
  audioContext: AudioContext,
  encoded: string,
): AudioBuffer | null {
  let binary: string
  try {
    binary = window.atob(encoded)
  } catch {
    return null
  }

  const sampleCount = Math.floor(binary.length / 2)
  if (sampleCount < 1) return null

  const samples = new Float32Array(sampleCount)
  for (let index = 0; index < sampleCount; index += 1) {
    const value = (binary.charCodeAt(index * 2) & 0xff)
      | ((binary.charCodeAt(index * 2 + 1) & 0xff) << 8)
    const signed = value >= 0x8000 ? value - 0x10000 : value
    samples[index] = signed < 0 ? signed / 0x8000 : signed / 0x7fff
  }

  const buffer = audioContext.createBuffer(1, sampleCount, OUTPUT_RATE)
  buffer.copyToChannel(samples, 0)
  return buffer
}

function boundedToolOutput(result: ToolResult): Record<string, unknown> {
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
  if (serialized.length <= 14000) return summary
  return { response: serialized.slice(0, 14000) }
}

function toolCallIdempotencyKey(id: string): string {
  const safe = id.replace(/[^A-Za-z0-9_-]/gu, "").slice(0, 90)
  return "nova-gemini-" + (safe || crypto.randomUUID())
}

function shouldRouteToNova(message: string): boolean {
  const normalized = message.trim().toLowerCase()
  if (!normalized) return false

  if (/\b(?:https?:\/\/|www\.)/u.test(normalized)) return true
  if (/\b(?:search|look up|research|google search|find out|browse the web)\b/u.test(normalized)) return true

  const freshness = /\b(?:latest|recent|current(?:ly)?|today(?:'s)?|live|right now|at the moment|real time|realtime|now|aaj|abhi|filhal)\b/u.test(normalized)
  const liveSubject = /\b(?:news|headlines?|weather|forecast|exchange rates?|stock prices?|score|scores|scorecard|match|matches|cricket|football|soccer|sports?|fixtures?|standings|playing|wickets?|innings|goals?)\b/u.test(normalized)
  const informationRequest = /\b(?:what|who|which|when|where|why|how|tell me|show me|give me|find|check|search|research|look up|score|scores|kya|batao|btao|kitna|kitne|kaun|dikhao|chal raha|ho raha)\b/u.test(normalized)
  if (freshness && liveSubject && informationRequest) return true

  // Current-score questions often imply freshness without saying "live".
  if (
    liveSubject
    && /\b(?:pak|pakistan|eng|england|india|ind|australia|aus|new zealand|nz|cricket|football|soccer|team|match)\b/u.test(normalized)
    && /\b(?:score|scores|scorecard|who(?:'s| is) playing|kya score|score chal|match ho raha)\b/u.test(normalized)
  ) return true

  const emailAction = /\b(?:send|compose|draft|read|search|check|open|reply|forward|delete|list|find)\b/u
  const emailTarget = /\b(?:email|e-mail|mail|gmail|inbox)\b/u
  if (emailAction.test(normalized) && emailTarget.test(normalized)) return true

  const personalAction = /\b(?:create|add|make|show|list|check|complete|start|cancel|delete|update|schedule|book|move|reschedule|remind|set)\b/u
  const personalTarget = /\b(?:task|reminder|calendar|meeting|appointment|event)\b/u
  if (personalAction.test(normalized) && personalTarget.test(normalized)) return true

  const desktopAction = /\b(?:open|launch|start|visit|go to|navigate to|show|find|inspect|check|click|tap|type|press|play|turn on|turn off|increase|decrease|raise|lower|mute|unmute|set)\b/u
  const desktopTarget = /\b(?:notepad|calculator|file explorer|browser|website|web site|app|application|folder|file|desktop|screen|downloads|documents|youtube|google|chrome|edge|firefox|settings|volume|brightness|wifi|wi-fi|bluetooth|spotify|local disk|c drive|computer|pc)\b/u
  return desktopAction.test(normalized) && desktopTarget.test(normalized)
}

function isLiveSearchRequest(message: string): boolean {
  const normalized = message.trim().toLowerCase()
  if (!normalized) return false

  const emailTarget = /\b(?:email|e-mail|mail|gmail|inbox)\b/u.test(normalized)
  const explicitWebSearch = /\b(?:search|look up|research|google search|find out|browse the web|web search)\b/u.test(normalized)
  if (explicitWebSearch && !emailTarget) return true

  const freshness = /\b(?:latest|recent|current(?:ly)?|today(?:'s)?|live|right now|at the moment|real time|realtime|now|aaj|abhi|filhal)\b/u.test(normalized)
  const liveSubject = /\b(?:news|headlines?|weather|forecast|prices?|rates?|stocks?|score|scores|scorecard|match|matches|cricket|football|soccer|sports?|fixtures?|standings|playing|wickets?|innings|goals?)\b/u.test(normalized)
  const informationRequest = /\b(?:what|who|which|when|where|why|how|tell me|show me|give me|find|check|kya|batao|btao|kitna|kitne|kaun|dikhao|chal raha|ho raha)\b/u.test(normalized)
  return liveSubject && informationRequest && (freshness || /\b(?:score|scores|scorecard)\b/u.test(normalized))
}

function extractVoiceSearchSources(value: unknown): VoiceSearchSource[] {
  if (!value || typeof value !== "object") return []
  const root = value as Record<string, unknown>
  let candidates: unknown[] = Array.isArray(root.web_sources) ? root.web_sources : []

  if (candidates.length === 0) {
    const toolResult = root.tool_result
    if (toolResult && typeof toolResult === "object") {
      const toolPayload = (toolResult as Record<string, unknown>).result
      if (toolPayload && typeof toolPayload === "object") {
        const results = (toolPayload as Record<string, unknown>).results
        if (Array.isArray(results)) candidates = results
      }
    }
  }

  const sources: VoiceSearchSource[] = []
  const seen = new Set<string>()
  for (const candidate of candidates) {
    if (!candidate || typeof candidate !== "object") continue
    const item = candidate as Record<string, unknown>
    const title = String(item.title ?? "").trim().slice(0, 180)
    const url = String(item.url ?? item.link ?? "").trim()
    const snippet = String(item.content ?? item.snippet ?? item.description ?? "").trim().slice(0, 420)
    const published = String(item.published_date ?? item.publishedDate ?? "").trim().slice(0, 60)
    if (!title || !url || seen.has(url)) continue
    try {
      const parsed = new URL(url)
      if (parsed.protocol !== "https:" && parsed.protocol !== "http:") continue
      seen.add(url)
      sources.push({
        title,
        url: parsed.href,
        snippet,
        publishedDate: published || null,
        host: parsed.hostname.replace(/^www\./u, ""),
      })
      if (sources.length >= 5) break
    } catch {
      // Provider output is untrusted; only render navigable HTTP(S) links.
    }
  }
  return sources
}

function liveSearchStatusFromResult(result: unknown, sources: VoiceSearchSource[], failure?: string): string {
  if (failure) return "Live search failed: " + failure.slice(0, 180)
  if (sources.length > 0) {
    return "Found " + sources.length + " search source" + (sources.length === 1 ? "" : "s")
  }
  if (result && typeof result === "object") {
    const root = result as Record<string, unknown>
    const toolResult = root.tool_result
    if (toolResult && typeof toolResult === "object") {
      const tool = toolResult as Record<string, unknown>
      if (tool.success === false && typeof tool.error === "string") {
        const safeError = tool.error.slice(0, 180)
        if (/^No verified live-score source/i.test(safeError)) return safeError
        return "Live search failed: " + safeError
      }
      const payload = tool.result
      if (payload && typeof payload === "object" && Array.isArray((payload as Record<string, unknown>).results)) {
        return "No verified live sources were returned; I won't guess the current score."
      }
    }
  }
  return "No verified live sources were returned; I won't guess the current score."
}

export function GeminiLiveVoiceSurface({
  onOpenConversation,
  voiceTransport = "gemini",
  onVoiceTransportChange = () => undefined,
  cloudMode = false,
}: {
  onOpenConversation: () => void
  voiceTransport?: VoiceTransport
  onVoiceTransportChange?: (value: VoiceTransport) => void
  cloudMode?: boolean
}) {
  const [state, setState] = useState<VoiceState>("ready")
  const stateRef = useRef(state)
  stateRef.current = state
  const [connected, setConnected] = useState(false)
  const [transcript, setTranscript] = useState("")
  const [response, setResponse] = useState("")
  const [turnHistory, setTurnHistory] = useState<VoiceTranscriptTurn[]>([])
  const [activeSearchStatus, setActiveSearchStatus] = useState<string | null>(null)
  const [activeSearchSources, setActiveSearchSources] = useState<VoiceSearchSource[]>([])
  const [error, setError] = useState<string | null>(null)
  const [audioState, setAudioState] = useState<"idle" | "preparing" | "playing">("idle")
  const [microphonePermission, setMicrophonePermission] = useState<"unknown" | "granted" | "denied">("unknown")
  const [voiceLanguage, setVoiceLanguage] = useState<VoiceLanguage>(() => getVoiceLanguagePreference())
  const [languageSettingsOpen, setLanguageSettingsOpen] = useState(false)

  const socketRef = useRef<WebSocket | null>(null)
  const setupTimeoutRef = useRef<number | null>(null)
  const transcriptPanelRef = useRef<HTMLDivElement | null>(null)
  const microphoneRef = useRef<MediaStream | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const audioSourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const workletRef = useRef<AudioWorkletNode | null>(null)
  const muteGainRef = useRef<GainNode | null>(null)
  const playbackGainRef = useRef<GainNode | null>(null)
  const playbackSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set())
  const playbackEndTimeRef = useRef(0)
  const workletUrlRef = useRef<string | null>(null)
  const conversationIdRef = useRef<number | null>(null)
  const activeTurnRef = useRef<ActiveTurn>(newTurn())
  const completedTurnIdsRef = useRef<Set<number>>(new Set())
  const handledToolCallsRef = useRef<Set<string>>(new Set())
  const connectedRef = useRef(false)
  const connectingRef = useRef(false)
  const intentionalCloseRef = useRef(false)
  const connectRef = useRef<(automatic?: boolean) => Promise<void>>(async () => undefined)
  const reconnectTimerRef = useRef<number | null>(null)
  const stableConnectionTimerRef = useRef<number | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const reconnectCancelledRef = useRef(false)
  const suppressPlaybackRef = useRef(false)
  const voiceLanguageRef = useRef(voiceLanguage)
  voiceLanguageRef.current = voiceLanguage
  useEffect(() => {
    const panel = transcriptPanelRef.current
    if (panel) panel.scrollTop = panel.scrollHeight
  }, [transcript, response, turnHistory, activeSearchStatus, activeSearchSources])

  const errorRef = useRef<string | null>(null)
  errorRef.current = error

  const stopPlayback = useCallback(() => {
    for (const source of playbackSourcesRef.current) {
      try {
        source.stop()
      } catch {
        // The source may already have ended.
      }
    }
    playbackSourcesRef.current.clear()
    playbackEndTimeRef.current = 0
    setAudioState("idle")
  }, [])

  const startSearchProgress = useCallback((turn: ActiveTurn, query: string) => {
    if (!isLiveSearchRequest(query)) return
    turn.searchStatus = "Searching live sources…"
    turn.searchSources = []
    if (activeTurnRef.current.id === turn.id) {
      setActiveSearchStatus(turn.searchStatus)
      setActiveSearchSources([])
    }
  }, [])

  const finishSearchProgress = useCallback((
    turn: ActiveTurn,
    query: string,
    result: unknown,
    failure?: string,
  ) => {
    if (!isLiveSearchRequest(query)) return
    const sources = extractVoiceSearchSources(result)
    const status = liveSearchStatusFromResult(result, sources, failure)
    turn.searchStatus = status
    turn.searchSources = sources
    if (activeTurnRef.current.id === turn.id) {
      setActiveSearchStatus(status)
      setActiveSearchSources(sources)
    }
  }, [])

  const releaseConnection = useCallback(() => {
    if (setupTimeoutRef.current !== null) {
      window.clearTimeout(setupTimeoutRef.current)
      setupTimeoutRef.current = null
    }
    if (stableConnectionTimerRef.current !== null) {
      window.clearTimeout(stableConnectionTimerRef.current)
      stableConnectionTimerRef.current = null
    }

    const socket = socketRef.current
    socketRef.current = null
    if (socket && socket.readyState !== WebSocket.CLOSED) {
      try {
        socket.close(1000, "NOVA voice stopped")
      } catch {
        // Continue releasing local audio devices.
      }
    }

    stopPlayback()
    workletRef.current?.disconnect()
    workletRef.current = null
    audioSourceRef.current?.disconnect()
    audioSourceRef.current = null
    muteGainRef.current?.disconnect()
    muteGainRef.current = null
    playbackGainRef.current?.disconnect()
    playbackGainRef.current = null
    microphoneRef.current?.getTracks().forEach((track) => track.stop())
    microphoneRef.current = null

    if (audioContextRef.current) {
      void audioContextRef.current.close().catch(() => undefined)
      audioContextRef.current = null
    }
    if (workletUrlRef.current) {
      URL.revokeObjectURL(workletUrlRef.current)
      workletUrlRef.current = null
    }

    connectedRef.current = false
    connectingRef.current = false
    setConnected(false)
    setAudioState("idle")
  }, [stopPlayback])

  const scheduleAutomaticReconnect = useCallback((reason: string) => {
    if (reconnectCancelledRef.current) return

    if (!navigator.onLine) {
      setError("Internet connection is unavailable. NOVA will reconnect when it returns.")
      setState("disconnected")
      return
    }

    if (reconnectAttemptsRef.current >= MAX_AUTOMATIC_RECONNECT_ATTEMPTS) {
      setError(
        reason
        + " Automatic reconnect stopped after "
        + MAX_AUTOMATIC_RECONNECT_ATTEMPTS
        + " attempts. Tap the orb to reconnect manually.",
      )
      setState("disconnected")
      return
    }

    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current)
    }

    const attempt = reconnectAttemptsRef.current + 1
    reconnectAttemptsRef.current = attempt
    const delay = AUTOMATIC_RECONNECT_DELAYS_MS[attempt - 1]
      ?? AUTOMATIC_RECONNECT_DELAYS_MS[AUTOMATIC_RECONNECT_DELAYS_MS.length - 1]

    setError(
      reason
      + " Retrying voice in "
      + Math.ceil(delay / 1_000)
      + "s (attempt "
      + attempt
      + " of "
      + MAX_AUTOMATIC_RECONNECT_ATTEMPTS
      + ").",
    )
    setState("connecting")

    reconnectTimerRef.current = window.setTimeout(() => {
      reconnectTimerRef.current = null
      if (reconnectCancelledRef.current) return
      if (!navigator.onLine) {
        setState("disconnected")
        setError("Internet connection is unavailable. NOVA will reconnect when it returns.")
        return
      }
      void connectRef.current(true)
    }, delay)
  }, [])

  const persistTurn = useCallback(() => {
    const turn = activeTurnRef.current
    if (
      !turn.responseDone
      || turn.cancelled
      || turn.toolUsed
      || turn.saveStarted
      || !turn.userText.trim()
      || !turn.assistantText.trim()
    ) return

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
    ).then((saved) => {
      conversationIdRef.current = saved.conversation_id
    }).catch(() => {
      turn.saveStarted = false
      setError("This voice turn could not be saved to NOVA conversation history.")
    })
  }, [])

  const sendToolCall = useCallback(async (message: GeminiMessage) => {
    const socket = socketRef.current
    const calls = Array.isArray(message.functionCalls) ? message.functionCalls : []
    if (!socket || socket.readyState !== WebSocket.OPEN || calls.length === 0) return

    const functionResponses: Array<Record<string, unknown>> = []
    // Freeze the source utterance for this batch. The user's finalized transcript
    // is authoritative for exact task titles, names, dates, and recipients; the
    // realtime model's function arguments can paraphrase or omit those details.
    const turn = activeTurnRef.current
    const sourceUtterance = turn.userText.trim()
    let executionClaimed = turn.toolUsed || turn.cancelled

    for (const call of calls) {
      const callId = typeof call.id === "string" ? call.id : ""
      const callName = typeof call.name === "string" ? call.name : ""
      if (!callId || callName !== "nova_execute_request" || handledToolCallsRef.current.has(callId)) {
        continue
      }

      handledToolCallsRef.current.add(callId)

      // One user turn may cross the authenticated NOVA execution boundary only
      // once. Multiple function calls in a provider response must never create
      // duplicate tasks/events or repeat external communication.
      if (executionClaimed) {
        functionResponses.push({
          id: callId,
          name: callName,
          response: {
            error: turn.cancelled
              ? "This user turn was interrupted and was not executed. Wait for the user's next request."
              : "A NOVA execution request was already submitted for this user turn. Use its result; do not repeat the action.",
            action_taken: false,
          },
        })
        continue
      }

      executionClaimed = true
      turn.toolUsed = true
      setState("thinking")
      setAudioState("preparing")

      let output: Record<string, unknown>
      let requestText = sourceUtterance
      try {
        const args = call.args && typeof call.args === "object"
          ? call.args as Record<string, unknown>
          : {}
        const modelRequest = typeof args.request === "string" ? args.request.trim() : ""
        requestText = sourceUtterance || modelRequest
        if (!requestText) {
          output = { error: "The NOVA request was empty. Ask the user to repeat it.", action_taken: false }
        } else {
          startSearchProgress(turn, requestText)
          const conversationId = conversationIdRef.current
          if (!conversationId) throw new Error("The NOVA conversation is not ready.")
          const result = await apiRequestWithRefresh<ToolResult>("/chat", {
            method: "POST",
            headers: { "Idempotency-Key": toolCallIdempotencyKey(callId) },
            body: JSON.stringify({ message: requestText, conversation_id: conversationId }),
          })
          finishSearchProgress(turn, requestText, result)
          output = boundedToolOutput(result)
        }
      } catch (toolError) {
        const messageText = readableError(toolError, "NOVA could not complete the request.")
        finishSearchProgress(turn, requestText, null, messageText)
        output = {
          error: messageText,
          action_taken: false,
        }
      }

      functionResponses.push({ id: callId, name: callName, response: output })
    }

    if (functionResponses.length && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ toolResponse: { functionResponses } }))
    }
  }, [finishSearchProgress, startSearchProgress])

  const routeUndelegatedAction = useCallback(async (
    turn: ActiveTurn,
    socket: WebSocket,
    pendingToolCalls: Array<{ id: string; name: string }> = [],
  ) => {
    const sourceUtterance = turn.userText.trim()
    if (
      !sourceUtterance
      || turn.toolUsed
      || turn.cancelled
      || socket.readyState !== WebSocket.OPEN
    ) return

    // The model started answering an action request without calling NOVA's
    // declared function. Route the finalized utterance through /chat exactly
    // once, then ask Gemini to speak the authoritative backend result.
    turn.toolUsed = true
    turn.responseDone = false
    turn.assistantText = ""
    suppressPlaybackRef.current = true
    stopPlayback()
    startSearchProgress(turn, sourceUtterance)
    setResponse(isLiveSearchRequest(sourceUtterance) ? "Searching live sources…" : "Working on that through NOVA…")
    setAudioState("preparing")
    setState("thinking")
    console.info("[NOVA Gemini Live] routing an undelegated action through NOVA", {
      turnId: turn.id,
    })

    try {
      const conversationId = conversationIdRef.current
      if (!conversationId) throw new Error("The NOVA conversation is not ready.")

      const result = await apiRequestWithRefresh<ToolResult>("/chat", {
        method: "POST",
        headers: {
          "Idempotency-Key": toolCallIdempotencyKey(
            "fallback-" + turn.id + "-" + crypto.randomUUID(),
          ),
        },
        body: JSON.stringify({
          message: sourceUtterance,
          conversation_id: conversationId,
        }),
      })

      finishSearchProgress(turn, sourceUtterance, result)
      const resultSummary = JSON.stringify(boundedToolOutput(result))
      if (socketRef.current !== socket || socket.readyState !== WebSocket.OPEN) {
        const answer = typeof result.response === "string" ? result.response : ""
        turn.assistantText = answer || "NOVA processed the request, but the voice connection closed before it could speak the result."
        turn.responseDone = true
        setResponse(turn.assistantText)
        setAudioState("idle")
        if (connectedRef.current) setState("ready")
        return
      }

      if (pendingToolCalls.length > 0) {
        // When Gemini emitted an unsupported/malformed function name, satisfy
        // that pending function call with the authoritative NOVA result. This
        // lets Gemini continue speaking without a second user-content turn.
        socket.send(JSON.stringify({
          toolResponse: {
            functionResponses: pendingToolCalls.map((call) => ({
              id: call.id,
              name: call.name,
              response: boundedToolOutput(result),
            })),
          },
        }))
        return
      }

      const instruction = [
        "NOVA has already processed the user's request through its authenticated backend.",
        "The following JSON is the authoritative result. Do not execute the request again and do not call any function.",
        "Speak a natural concise answer in the user's language based only on this result. Be transparent about failure or required confirmation; never claim success unless the result says so.",
        "Backend result: " + resultSummary,
      ].join("\n")

      // This is a follow-up spoken turn, not a function response: no model
      // function call was received for the original request.
      suppressPlaybackRef.current = false
      setResponse("")
      setAudioState("preparing")
      socket.send(JSON.stringify({
        clientContent: {
          turns: [{
            role: "user",
            parts: [{ text: instruction }],
          }],
          turnComplete: true,
        },
      }))
    } catch (routeError) {
      suppressPlaybackRef.current = false
      const message = readableError(routeError, "NOVA could not complete the request.")
      finishSearchProgress(turn, sourceUtterance, null, message)
      if (pendingToolCalls.length > 0 && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
          toolResponse: {
            functionResponses: pendingToolCalls.map((call) => ({
              id: call.id,
              name: call.name,
              response: { success: false, action_taken: false, error: message },
            })),
          },
        }))
        return
      }
      turn.assistantText = message
      turn.responseDone = true
      setResponse(message)
      setAudioState("idle")
      if (connectedRef.current) setState("ready")
      setError(message)
      completedTurnIdsRef.current.add(turn.id)
      setTurnHistory((current) => [
        ...current,
        {
          id: turn.id,
          userText: sourceUtterance,
          assistantText: message,
          searchStatus: turn.searchStatus,
          searchSources: turn.searchSources,
        },
      ].slice(-40))
    }
  }, [finishSearchProgress, startSearchProgress, stopPlayback])

  const handleServerMessage = useCallback((message: GeminiMessage) => {
    const socket = socketRef.current
    if (!socket) return

    if (message.setupComplete) {
      if (setupTimeoutRef.current !== null) {
        window.clearTimeout(setupTimeoutRef.current)
        setupTimeoutRef.current = null
      }
      console.info("[NOVA Gemini Live] session setup completed")
      connectedRef.current = true
      connectingRef.current = false
      if (stableConnectionTimerRef.current !== null) {
        window.clearTimeout(stableConnectionTimerRef.current)
      }
      stableConnectionTimerRef.current = window.setTimeout(() => {
        stableConnectionTimerRef.current = null
        if (connectedRef.current) reconnectAttemptsRef.current = 0
      }, CONNECTION_STABILITY_WINDOW_MS)
      setConnected(true)
      setState("ready")
      setAudioState("idle")
      setError(null)
      return
    }

    if (message.goAway) {
      setError("Gemini Live session is nearing its configured lifetime. Finish this turn and reconnect.")
      return
    }

    // Handle Gemini function calls before serverContent. A valid NOVA call
    // claims this turn synchronously, preventing the generic fallback from
    // racing it. Unknown/malformed call names on an actionable turn are routed
    // through /chat and answered using the original function-call IDs.
    if (message.toolCall && typeof message.toolCall === "object") {
      const toolCall = message.toolCall as GeminiMessage
      const calls = Array.isArray(toolCall.functionCalls) ? toolCall.functionCalls : []
      const supportedCalls = calls.filter(
        (call: GeminiMessage) => call?.name === "nova_execute_request",
      )
      if (supportedCalls.length > 0) {
        void sendToolCall(toolCall)
      } else {
        const turn = activeTurnRef.current
        const pendingCalls = calls.filter(
          (call: GeminiMessage) =>
            typeof call?.id === "string"
            && call.id.length > 0
            && typeof call?.name === "string"
            && call.name.length > 0,
        ).map((call: GeminiMessage) => ({
          id: call.id as string,
          name: call.name as string,
        }))
        if (
          shouldRouteToNova(turn.userText)
          && !turn.toolUsed
          && !turn.cancelled
        ) {
          void routeUndelegatedAction(turn, socket, pendingCalls)
          return
        }
        if (pendingCalls.length > 0 && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({
            toolResponse: {
              functionResponses: pendingCalls.map((call) => ({
                id: call.id,
                name: call.name,
                response: {
                  success: false,
                  action_taken: false,
                  error: "Unsupported NOVA function. Submit user requests through nova_execute_request.",
                },
              })),
            },
          }))
        }
      }
    }

    const serverContent = message.serverContent
    if (serverContent && typeof serverContent === "object") {
      if (serverContent.interrupted === true) {
        activeTurnRef.current.cancelled = true
        suppressPlaybackRef.current = false
        stopPlayback()
        setState("listening")
      }

      const inputChunk = typeof serverContent.inputTranscription?.text === "string"
        ? serverContent.inputTranscription.text
        : ""
      if (inputChunk) {
        const current = activeTurnRef.current
        if (current.responseDone || current.saveStarted || current.toolUsed || current.cancelled) {
          activeTurnRef.current = newTurn()
          setResponse("")
          setTranscript("")
          setActiveSearchStatus(null)
          setActiveSearchSources([])
        }
        const turn = activeTurnRef.current
        turn.userText = appendTranscript(turn.userText, inputChunk)
        setTranscript(turn.userText)
        if (stateRef.current !== "speaking" && stateRef.current !== "thinking") setState("listening")
      }

      const outputChunk = typeof serverContent.outputTranscription?.text === "string"
        ? serverContent.outputTranscription.text
        : ""
      const parts = Array.isArray(serverContent.modelTurn?.parts)
        ? serverContent.modelTurn.parts
        : []
      const hasModelOutput = Boolean(outputChunk.trim())
        || parts.some((part: GeminiMessage) => {
          const inlineData = part?.inlineData ?? part?.inline_data
          return (
            (typeof inlineData?.data === "string" && inlineData.data.length > 0)
            || (typeof part?.text === "string" && part.text.trim().length > 0)
          )
        })
        || serverContent.turnComplete === true
      const turn = activeTurnRef.current
      const interactionStatus = String(serverContent.interactionStatus ?? "").toUpperCase()
      const intermediateThinkingTurn = (
        serverContent.turnComplete === true
        && interactionStatus === "IN_PROGRESS"
      )

      // Gemini Live can finish an interim spoken segment while still working
      // on a tool call. This is not the final answer: keep the turn open and
      // show immediate progress instead of archiving a filler as the response.
      if (intermediateThinkingTurn && isLiveSearchRequest(turn.userText)) {
        startSearchProgress(turn, turn.userText)
      }
      if (hasModelOutput && !intermediateThinkingTurn
        && !turn.toolUsed
        && !turn.cancelled
        && shouldRouteToNova(turn.userText)
      ) {
        void routeUndelegatedAction(turn, socket)
        return
      }

      if (outputChunk) {
        const turn = activeTurnRef.current
        turn.assistantText = appendTranscript(turn.assistantText, outputChunk)
        setResponse(turn.assistantText)
        setAudioState((current) => current === "idle" ? "preparing" : current)
        setState("speaking")
      }

      for (const part of parts) {
        const inlineData = part?.inlineData ?? part?.inline_data
        const encoded = typeof inlineData?.data === "string" ? inlineData.data : ""
        const mimeType = typeof inlineData?.mimeType === "string"
          ? inlineData.mimeType
          : typeof inlineData?.mime_type === "string"
            ? inlineData.mime_type
            : ""
        if (encoded && mimeType.toLowerCase().startsWith("audio/pcm")) {
          if (suppressPlaybackRef.current) continue
          const context = audioContextRef.current
          if (!context || context.state === "closed") continue
          const buffer = base64PcmToAudioBuffer(context, encoded)
          if (!buffer || !playbackGainRef.current) continue

          const source = context.createBufferSource()
          source.buffer = buffer
          source.connect(playbackGainRef.current)
          source.onended = () => {
            playbackSourcesRef.current.delete(source)
            if (playbackSourcesRef.current.size === 0 && activeTurnRef.current.responseDone) {
              playbackEndTimeRef.current = context.currentTime
              setAudioState("idle")
              if (connectedRef.current && !activeTurnRef.current.cancelled) setState("ready")
            }
          }
          const startAt = Math.max(context.currentTime + 0.02, playbackEndTimeRef.current)
          source.start(startAt)
          playbackEndTimeRef.current = startAt + buffer.duration
          playbackSourcesRef.current.add(source)
          setAudioState("playing")
          setState("speaking")
        } else if (typeof part?.text === "string" && part.text.trim()) {
          const turn = activeTurnRef.current
          turn.assistantText = appendTranscript(turn.assistantText, part.text)
          setResponse(turn.assistantText)
        }
      }

      if (serverContent.turnComplete === true && interactionStatus === "IN_PROGRESS") {
        // Keep the microphone/session active while Gemini performs the tool step.
        // The next toolResponse and final IDLE turn belong to the same exchange.
        if (playbackSourcesRef.current.size === 0) {
          setAudioState("idle")
          if (connectedRef.current) setState("thinking")
        } else {
          setState("speaking")
        }
      } else if (serverContent.turnComplete === true) {
        if (suppressPlaybackRef.current) suppressPlaybackRef.current = false
        const turn = activeTurnRef.current
        turn.responseDone = true
        persistTurn()

        // Only final turns are archived. Gemini Live can emit an interim
        // turnComplete with IN_PROGRESS first.
        const archivedTurn = {
          id: turn.id,
          userText: turn.userText.trim(),
          assistantText: turn.assistantText.trim(),
          searchStatus: turn.searchStatus,
          searchSources: turn.searchSources,
        }
        if (
          !turn.cancelled
          && (archivedTurn.userText || archivedTurn.assistantText)
          && !completedTurnIdsRef.current.has(turn.id)
        ) {
          completedTurnIdsRef.current.add(turn.id)
          setTurnHistory((current) => [...current, archivedTurn].slice(-40))
        }

        if (playbackSourcesRef.current.size === 0) {
          setAudioState("idle")
          if (connectedRef.current) setState("ready")
        } else {
          setState("speaking")
        }
      }
    }

    if (message.toolCallCancellation) {
      activeTurnRef.current.cancelled = true
      setAudioState("idle")
    }

    if (message.error && typeof message.error === "object") {
      const providerError = message.error as Record<string, unknown>
      const code = String(providerError.status ?? providerError.code ?? providerError.type ?? "UNKNOWN")
      const providerMessage = typeof providerError.message === "string"
        ? providerError.message.trim().replace(/\s+/gu, " ").slice(0, 180)
        : ""
      const permanentProviderError = /RESOURCE_EXHAUSTED|429|UNAUTHENTICATED|PERMISSION_DENIED|INVALID_ARGUMENT|quota|rate limit|unauthenticated|permission denied|invalid api key|not configured/i
        .test(code + " " + providerMessage)
      reconnectCancelledRef.current = permanentProviderError
      console.error("[NOVA Gemini Live] server rejected the session", {
        code,
        message: providerMessage,
      })
      if (code === "RESOURCE_EXHAUSTED" || code === "429") {
        setError("Gemini Live free-tier quota or rate limit was reached. Check AI Studio usage and wait for quota reset; paid billing is not automatically required.")
      } else if (code === "UNAUTHENTICATED" || code === "PERMISSION_DENIED") {
        setError("Gemini Live rejected the API project or ephemeral token. Check the API key and Live model access in Google AI Studio.")
      } else {
        setError(
          "Google rejected NOVA's Live session setup ("
          + code
          + "). "
          + (providerMessage || "See the browser console for the provider error."),
        )
      }
      setState("disconnected")
      intentionalCloseRef.current = true
      releaseConnection()
      if (!permanentProviderError) {
        scheduleAutomaticReconnect("Gemini Live ended unexpectedly.")
      }
    }
  }, [persistTurn, releaseConnection, routeUndelegatedAction, scheduleAutomaticReconnect, sendToolCall, startSearchProgress, stopPlayback])

  const connect = useCallback(async (automatic = false) => {
    if (connectingRef.current || connectedRef.current) return
    if (automatic && reconnectCancelledRef.current) return
    if (!automatic) {
      reconnectCancelledRef.current = false
      reconnectAttemptsRef.current = 0
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === "undefined") {
      setState("disconnected")
      setError("This browser does not support the realtime microphone audio required by Gemini Live.")
      return
    }

    connectingRef.current = true
    intentionalCloseRef.current = false
    setState("connecting")
    setError(null)
    setAudioState("preparing")

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          // Prefer suppressing all speaker playback, including Web Audio output.
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
          { method: "POST", body: JSON.stringify({ title: "NOVA Voice Conversation" }) },
        )
        conversationIdRef.current = conversation.id
      }

      const tokenPath = "/voice/gemini/token?conversation_id="
        + encodeURIComponent(String(conversationIdRef.current))
        + "&language=" + encodeURIComponent(voiceLanguageRef.current)
      const tokenData = await apiRequestWithRefresh<GeminiTokenResponse>(tokenPath, { method: "POST" })
      if (!tokenData.token || !tokenData.model || !tokenData.config) {
        throw new Error("NOVA received an incomplete Gemini Live session token.")
      }

      const context = new AudioContext()
      audioContextRef.current = context
      await context.resume()
      const playbackGain = context.createGain()
      playbackGain.gain.value = 1
      playbackGain.connect(context.destination)
      playbackGainRef.current = playbackGain

      const workletUrl = URL.createObjectURL(
        new Blob([PCM_WORKLET_SOURCE], { type: "text/javascript" }),
      )
      workletUrlRef.current = workletUrl
      await context.audioWorklet.addModule(workletUrl)

      const worklet = new AudioWorkletNode(context, "nova-gemini-pcm-processor")
      workletRef.current = worklet
      const source = context.createMediaStreamSource(stream)
      audioSourceRef.current = source
      const muteGain = context.createGain()
      muteGain.gain.value = 0
      muteGainRef.current = muteGain
      source.connect(worklet)
      worklet.connect(muteGain)
      muteGain.connect(context.destination)

      const socketUrl = "wss://generativelanguage.googleapis.com/ws/"
        + "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained"
        + "?access_token=" + encodeURIComponent(tokenData.token)
      const socket = new WebSocket(socketUrl)
      socketRef.current = socket
      setupTimeoutRef.current = window.setTimeout(() => {
        if (socketRef.current !== socket || connectedRef.current) return
        console.error("[NOVA Gemini Live] setup handshake timed out", {
          readyState: socket.readyState,
        })
        const stageMessage = socket.readyState === WebSocket.CONNECTING
          ? "The secure WebSocket never opened."
          : socket.readyState === WebSocket.OPEN
            ? "The WebSocket opened, but Google did not acknowledge the setup frame."
            : "The WebSocket closed before setup finished."
        setError(
          "Gemini Live received a token, but setup failed after 12 seconds. "
          + stageMessage
          + " (WebSocket state "
          + socket.readyState
          + "). The session was stopped instead of staying on CONNECTING.",
        )
        intentionalCloseRef.current = true
        releaseConnection()
        setState("disconnected")
        scheduleAutomaticReconnect("Gemini Live setup timed out.")
      }, 12000)

      worklet.port.onmessage = (event: MessageEvent) => {
        if (event.data?.type === "voice-start") {
          const turn = activeTurnRef.current
          if (turn.responseDone || turn.saveStarted || turn.toolUsed || turn.cancelled) {
            activeTurnRef.current = newTurn()
            setResponse("")
            setTranscript("")
            setActiveSearchStatus(null)
            setActiveSearchSources([])
          }
          if (connectedRef.current && stateRef.current !== "speaking") setState("listening")
          return
        }
        if (!(event.data instanceof ArrayBuffer)) return
        if (socket.readyState !== WebSocket.OPEN || !connectedRef.current) return
        socket.send(JSON.stringify({
          realtimeInput: {
            audio: {
              data: bytesToBase64(event.data),
              mimeType: "audio/pcm;rate=" + INPUT_RATE,
            },
          },
        }))
      }

      socket.onopen = () => {
        if (socketRef.current !== socket) return
        console.info("[NOVA Gemini Live] WebSocket opened; sending constrained-token setup")
        // The raw WebSocket protocol requires the first setup frame to carry
        // a complete BidiGenerateContentSetup. The ephemeral token constrains the
        // effective session config server-side, but the client still sends the
        // same documented setup shape so the server can complete the handshake.
        socket.send(JSON.stringify({
          setup: {
            model: tokenData.model,
            ...tokenData.config,
          },
        }))
      }

      // Gemini Live can deliver setupComplete as a binary WebSocket frame.
      // Ask for ArrayBuffer frames and decode both binary and text payloads;
      // ignoring non-string event.data leaves the session stuck until timeout.
      socket.binaryType = "arraybuffer"
      socket.onmessage = async (event: MessageEvent) => {
        if (socketRef.current !== socket) return
        try {
          let payload: string
          if (typeof event.data === "string") {
            payload = event.data
          } else if (event.data instanceof ArrayBuffer) {
            payload = new TextDecoder().decode(event.data)
          } else if (event.data instanceof Blob) {
            payload = await event.data.text()
          } else {
            throw new Error("Unsupported Gemini Live WebSocket frame type.")
          }

          if (socketRef.current !== socket) return
          const message = JSON.parse(payload) as GeminiMessage
          console.debug("[NOVA Gemini Live] server event", Object.keys(message))
          handleServerMessage(message)
        } catch (messageError) {
          console.error("[NOVA Gemini Live] failed to process a server event", messageError)
          setError("NOVA received an unreadable Gemini Live event. Check the browser console for the event stage.")
          intentionalCloseRef.current = true
          releaseConnection()
          setState("disconnected")
        }
      }

      socket.onerror = () => {
        if (socketRef.current !== socket) return
        console.error("[NOVA Gemini Live] WebSocket transport error", {
          readyState: socket.readyState,
        })
        setError("Gemini Live WebSocket transport failed before the session finished setting up.")
        intentionalCloseRef.current = true
        releaseConnection()
        setState("disconnected")
        scheduleAutomaticReconnect("Gemini Live WebSocket transport failed.")
      }

      socket.onclose = (event) => {
        if (intentionalCloseRef.current || socketRef.current !== socket) return
        if (setupTimeoutRef.current !== null) {
          window.clearTimeout(setupTimeoutRef.current)
          setupTimeoutRef.current = null
        }
        console.warn("[NOVA Gemini Live] WebSocket closed", {
          code: event.code,
          reason: event.reason.slice(0, 160),
          hadCompletedSetup: connectedRef.current,
        })
        connectedRef.current = false
        connectingRef.current = false
        setConnected(false)
        const closeDescription = "Gemini Live WebSocket closed before NOVA finished connecting (code "
          + event.code
          + (event.reason ? ": " + event.reason.slice(0, 120) : "")
          + ")."
        const retryableClose = event.code !== 1008
          || /expir|session|lifetime|temporar|unavailable/i.test(event.reason)
        if (!retryableClose) {
          reconnectCancelledRef.current = true
          setError(closeDescription + " Reconnect manually after checking the session configuration.")
        } else if (!errorRef.current) {
          setError(closeDescription)
        }
        releaseConnection()
        setState("disconnected")
        if (retryableClose) scheduleAutomaticReconnect(closeDescription)
      }
    } catch (connectError) {
      const mediaError = connectError instanceof DOMException
        && (connectError.name === "NotAllowedError" || connectError.name === "PermissionDeniedError")
      if (mediaError) setMicrophonePermission("denied")
      const message = readableError(connectError, "NOVA could not start Gemini Live voice. Check microphone permission and try again.")
      setError(message)
      intentionalCloseRef.current = true
      releaseConnection()
      setState("disconnected")
      const errorName = connectError instanceof Error ? connectError.name : ""
      const retryableSetupError = !mediaError
        && !["NotFoundError", "SecurityError"].includes(errorName)
        && !/\b(429|quota|rate limit|unauthenticated|unauthorized|forbidden|permission denied|not configured|invalid api key|model access|billing)\b/i.test(message)
      if (retryableSetupError) {
        scheduleAutomaticReconnect("Gemini Live could not finish connecting.")
      } else {
        reconnectCancelledRef.current = true
      }
    } finally {
      connectingRef.current = false
    }
  }, [handleServerMessage, releaseConnection, scheduleAutomaticReconnect])

  connectRef.current = connect

  const stopSession = useCallback(() => {
    reconnectCancelledRef.current = true
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    reconnectAttemptsRef.current = 0
    intentionalCloseRef.current = true
    releaseConnection()
    setError(null)
    setState("ready")
  }, [releaseConnection])

  const interruptResponse = useCallback(() => {
    activeTurnRef.current.cancelled = true
    suppressPlaybackRef.current = true
    stopPlayback()
    // Keep the microphone stream open. Gemini's server-side VAD interrupts the
    // generation when the user starts speaking, without ending the input stream.
    setState(connectedRef.current ? "listening" : "disconnected")
  }, [stopPlayback])

  useEffect(() => {
    const onOnline = () => {
      setError(null)
      if (
        reconnectCancelledRef.current
        || connectedRef.current
        || connectingRef.current
        || stateRef.current !== "disconnected"
      ) return

      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      reconnectAttemptsRef.current = 0
      setState("connecting")
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null
        if (!reconnectCancelledRef.current && navigator.onLine) {
          void connectRef.current(true)
        }
      }, 250)
    }
    const onOffline = () => {
      setError("Internet connection is unavailable. NOVA will reconnect when it returns.")
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      if (!connectedRef.current) setState("disconnected")
    }
    window.addEventListener("online", onOnline)
    window.addEventListener("offline", onOffline)
    return () => {
      window.removeEventListener("online", onOnline)
      window.removeEventListener("offline", onOffline)
      reconnectCancelledRef.current = true
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      intentionalCloseRef.current = true
      releaseConnection()
    }
  }, [releaseConnection])

  const changeLanguage = (value: VoiceLanguage) => {
    setVoiceLanguage(value)
    setVoiceLanguagePreference(value)
    if (connectedRef.current) {
      setError("Language preference applies to the next session. Pause voice and reconnect to apply it.")
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

  const buttonLabel = state === "connecting"
    ? "Connecting…"
    : state === "disconnected"
      ? "Reconnect voice"
      : state === "thinking" || state === "speaking"
        ? "Interrupt & talk"
        : connected
          ? state === "listening" ? "Pause listening" : "Pause voice"
          : "Talk to NOVA"
  const statusLabel = state === "ready" && !connected
    ? "VOICE STANDBY"
    : state === "ready" && connected
      ? "READY TO LISTEN"
      : state.toUpperCase()

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
          <div className={"voice-live-state " + state}>{statusLabel}</div>
        </div>

        {!cloudMode && (
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
        )}
      </header>

      <main className="voice-main gemini-live-main">
        <section className="voice-stage gemini-live-stage" aria-label="NOVA Gemini Live voice session">
          <button
            className={"voice-orb gemini-live-orb voice-orb-" + state}
            type="button"
            onClick={handleVoiceButton}
            disabled={state === "connecting"}
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

          <div
            ref={transcriptPanelRef}
            className="voice-live-transcript gemini-live-transcript"
            aria-label="Live voice conversation"
            aria-live="polite"
            aria-relevant="additions text"
          >
            {turnHistory.map((turn) => (
              <div className="voice-turn-group" key={turn.id}>
                {turn.userText && (
                  <div className="voice-turn-card user">
                    <p>{turn.userText}</p>
                  </div>
                )}
                {turn.assistantText && (
                  <div className="voice-turn-card assistant">
                    <p>{turn.assistantText}</p>
                  </div>
                )}
                {turn.searchStatus && (
                  <div className={"gemini-live-search-status " + (turn.searchStatus.startsWith("Searching") ? "loading" : "complete")} role="status">
                    <span className="gemini-live-search-indicator" aria-hidden="true" />
                    <span>{turn.searchStatus}</span>
                  </div>
                )}
                {turn.searchSources.length > 0 && (
                  <div className="gemini-live-search-sources" aria-label="Live search sources">
                    {turn.searchSources.map((source) => (
                      <a
                        className="gemini-live-search-source"
                        key={source.url}
                        href={source.url}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        <span className="gemini-live-search-host">{source.host}</span>
                        <strong>{source.title}</strong>
                        {source.snippet && <p>{source.snippet}</p>}
                        {source.publishedDate && <small>Published {source.publishedDate}</small>}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {!completedTurnIdsRef.current.has(activeTurnRef.current.id) && (
              <>
                {!transcript && !response && turnHistory.length === 0 && (
                  <p className="voice-transcript-placeholder">
                    {connected
                      ? state === "listening"
                        ? "I'm listening. Your words will appear here."
                        : "Speak naturally — your conversation will appear here."
                      : state === "connecting"
                        ? "Connecting to NOVA voice…"
                        : state === "disconnected"
                          ? "Voice is disconnected. Reconnect to continue."
                          : "Tap the orb to start a voice conversation."}
                  </p>
                )}
                {transcript && (
                  <div className="voice-turn-card user current">
                    <p>{transcript}</p>
                  </div>
                )}
                {response && (
                  <div className="voice-turn-card assistant current">
                    <div className="voice-turn-label">
                      <span>NOVA</span>
                      {audioState !== "idle" && (
                        <span className={"voice-audio-label " + audioState}>
                          {audioState === "playing" ? "AUDIO LIVE" : "PREPARING AUDIO"}
                        </span>
                      )}
                    </div>
                    {audioState !== "idle" && (
                      <div className={"voice-audio-status " + audioState} role="status">
                        <span className="voice-audio-bars" aria-hidden="true">
                          <i /><i /><i /><i /><i />
                        </span>
                        <span>{audioState === "playing" ? "NOVA is speaking" : "Preparing realtime response"}</span>
                      </div>
                    )}
                    <p>{response}</p>
                  </div>
                )}
                {activeSearchStatus && (
                  <div className={"gemini-live-search-status " + (activeSearchStatus.startsWith("Searching") ? "loading" : "complete")} role="status">
                    <span className="gemini-live-search-indicator" aria-hidden="true" />
                    <span>{activeSearchStatus}</span>
                  </div>
                )}
                {activeSearchSources.length > 0 && (
                  <div className="gemini-live-search-sources" aria-label="Live search sources">
                    {activeSearchSources.map((source) => (
                      <a
                        className="gemini-live-search-source"
                        key={source.url}
                        href={source.url}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        <span className="gemini-live-search-host">{source.host}</span>
                        <strong>{source.title}</strong>
                        {source.snippet && <p>{source.snippet}</p>}
                        {source.publishedDate && <small>Published {source.publishedDate}</small>}
                      </a>
                    ))}
                  </div>
                )}
              </>
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
              {!cloudMode && (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      const classicUrl = new URL(window.location.href)
                      classicUrl.searchParams.set("voice_transport", "legacy")
                      window.location.assign(classicUrl.toString())
                    }}
                  >
                    Use classic voice
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const openaiUrl = new URL(window.location.href)
                      openaiUrl.searchParams.set("voice_transport", "openai")
                      window.location.assign(openaiUrl.toString())
                    }}
                  >
                    Try OpenAI Realtime
                  </button>
                </>
              )}
            </div>
          )}

          {microphonePermission === "denied" && (
            <small className="voice-microphone-state voice-microphone-warning" role="status">
              Microphone access is blocked in browser settings.
            </small>
          )}

          {!cloudMode && languageSettingsOpen && (
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
          <span>{connected ? "Gemini Live · hands-free turn taking" : "Start voice to enable your microphone"}</span>
          <span className="voice-footer-divider" aria-hidden="true">·</span>
          <span>{connected ? "Speak naturally; interrupt any time" : "Native speech-to-speech · free tier"}</span>
        </footer>
      </main>
    </div>
  )
}
