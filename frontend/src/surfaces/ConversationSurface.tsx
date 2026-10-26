import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"

import { parseApiDateTime } from "../app/datetime"
import { getVoiceLanguagePreference } from "../app/voiceLanguage"
import { ApiRequestError, getAccessToken } from "../api/client"
import { API_BASE_URL } from "../app/config"
import {
  createConversation,
  deleteConversation,
  getConversationMessages,
  getConversationState,
  getConversations,
  sendChatMessage,
  updateConversationTitle,
  type ConversationState,
} from "../api/conversations"
import type { ChatResponse, Conversation, ConversationMessage } from "../api/types"
import {
  approveAndExecuteConfirmation,
  rejectConfirmation,
} from "../api/workspace"
import { Icon } from "../components/Icon"

type RetryPayload = {
  message: string
  conversationId: number | null
  idempotencyKey: string
}

type DictationTranscriptEvent = {
  type?: string
  text?: string
  is_end_of_speech?: boolean
}

type DictationSocketMessage = {
  type?: string
  text?: string
  message?: string
  code?: string
  event?: DictationTranscriptEvent
}

const DICTATION_PCM_WORKLET_SOURCE = `
class NovaDictationPcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buffer = new Float32Array(0)
    this.position = 0
    this.targetRate = 16000
    this.chunkSize = 320
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (!channel) return true

    const merged = new Float32Array(this.buffer.length + channel.length)
    merged.set(this.buffer)
    merged.set(channel, this.buffer.length)
    this.buffer = merged

    const step = sampleRate / this.targetRate
    while (this.position + (this.chunkSize - 1) * step < this.buffer.length) {
      const pcm = new Int16Array(this.chunkSize)
      for (let index = 0; index < this.chunkSize; index += 1) {
        const position = this.position + index * step
        const leftIndex = Math.floor(position)
        const fraction = position - leftIndex
        const left = this.buffer[leftIndex] || 0
        const right = this.buffer[leftIndex + 1] ?? left
        const sample = Math.max(-1, Math.min(1, left + (right - left) * fraction))
        pcm[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
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
registerProcessor("nova-dictation-pcm", NovaDictationPcmProcessor)
`

function buildDictationWebSocketUrl(): string {
  if (!API_BASE_URL) {
    throw new Error("NOVA API endpoint is not configured.")
  }
  return `${API_BASE_URL.replace(/^http/, "ws")}/voice/dictation/ws?language=${encodeURIComponent(getVoiceLanguagePreference())}`
}

function mergeDictationTranscript(confirmed: string, latest: string): string {
  const previous = confirmed.trim()
  const next = latest.trim()
  if (!previous) return next
  if (!next) return previous
  if (next === previous || next.startsWith(`${previous} `)) return next
  if (previous.endsWith(next)) return previous
  return `${previous} ${next}`.trim()
}

function requestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `nova-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function formatTime(value: string): string {
  const date = parseApiDateTime(value)
  if (Number.isNaN(date.getTime())) return ""
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()

  return new Intl.DateTimeFormat(
    undefined,
    sameDay
      ? { hour: "numeric", minute: "2-digit" }
      : { month: "short", day: "numeric" },
  ).format(date)
}

function formatApiError(err: unknown, fallback: string): string {
  return err instanceof ApiRequestError ? err.detail : fallback
}

export function ConversationSurface() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [conversationState, setConversationState] = useState<ConversationState | null>(null)
  const [assistantMeta, setAssistantMeta] = useState<ChatResponse | null>(null)
  const [confirmationBusy, setConfirmationBusy] = useState<"approve" | "reject" | null>(null)
  const [confirmationNotice, setConfirmationNotice] = useState<string | null>(null)
  const [creatingConversation, setCreatingConversation] = useState(false)
  const [draft, setDraft] = useState("")
  const [keyboardTyping, setKeyboardTyping] = useState(false)
  const [voiceTyping, setVoiceTyping] = useState(false)
  const [voiceFinalizing, setVoiceFinalizing] = useState(false)
  const [voiceTypingMessage, setVoiceTypingMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [sending, setSending] = useState(false)
  const [savingId, setSavingId] = useState<number | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingTitle, setEditingTitle] = useState("")
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [errorAction, setErrorAction] = useState<"retry" | null>(null)
  const [retryPayload, setRetryPayload] = useState<RetryPayload | null>(null)
  const [showScrollToBottom, setShowScrollToBottom] = useState(false)
  const messageScrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const messageLoadRequestRef = useRef(0)
  const shouldAutoScrollRef = useRef(true)
  const dictationSocketRef = useRef<WebSocket | null>(null)
  const dictationStreamRef = useRef<MediaStream | null>(null)
  const dictationAudioContextRef = useRef<AudioContext | null>(null)
  const dictationSourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const dictationWorkletRef = useRef<AudioWorkletNode | null>(null)
  const dictationMuteGainRef = useRef<GainNode | null>(null)
  const dictationModuleUrlRef = useRef<string | null>(null)
  const dictationFinalizingRef = useRef(false)
  const voiceDraftPrefixRef = useRef("")
  const confirmedTranscriptRef = useRef("")
  const partialTranscriptRef = useRef("")

  useEffect(() => {
    try {
      if (activeId !== null) {
        window.sessionStorage.setItem("nova_active_conversation_id", String(activeId))
      } else if (!loading && conversations.length === 0) {
        window.sessionStorage.removeItem("nova_active_conversation_id")
      }
    } catch {
      // Conversation selection works even when browser storage is blocked.
    }
  }, [activeId, loading, conversations.length])

  const releaseDictationAudio = useCallback(() => {
    if (dictationWorkletRef.current) {
      dictationWorkletRef.current.port.onmessage = null
      dictationWorkletRef.current.disconnect()
      dictationWorkletRef.current = null
    }
    if (dictationSourceRef.current) {
      dictationSourceRef.current.disconnect()
      dictationSourceRef.current = null
    }
    if (dictationMuteGainRef.current) {
      dictationMuteGainRef.current.disconnect()
      dictationMuteGainRef.current = null
    }
    if (dictationStreamRef.current) {
      for (const track of dictationStreamRef.current.getTracks()) track.stop()
      dictationStreamRef.current = null
    }
    const audioContext = dictationAudioContextRef.current
    dictationAudioContextRef.current = null
    if (audioContext && audioContext.state !== "closed") {
      void audioContext.close().catch(() => undefined)
    }
    if (dictationModuleUrlRef.current) {
      URL.revokeObjectURL(dictationModuleUrlRef.current)
      dictationModuleUrlRef.current = null
    }
  }, [])

  const cancelVoiceTyping = useCallback(() => {
    const socket = dictationSocketRef.current
    dictationSocketRef.current = null
    dictationFinalizingRef.current = false
    releaseDictationAudio()
    if (socket && socket.readyState === WebSocket.OPEN) {
      try {
        socket.send(JSON.stringify({ type: "dictation.cancel" }))
      } catch {
        // Socket closure below still cancels the active dictation turn.
      }
    }
    if (socket && socket.readyState !== WebSocket.CLOSED) socket.close()
    setVoiceTyping(false)
    setVoiceFinalizing(false)
    setVoiceTypingMessage(null)
  }, [releaseDictationAudio])

  const finishVoiceTyping = useCallback(() => {
    const socket = dictationSocketRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      cancelVoiceTyping()
      setVoiceTypingMessage("Dictation connection was lost. Click the microphone to try again.")
      return
    }

    dictationFinalizingRef.current = true
    setVoiceTyping(false)
    setVoiceFinalizing(true)
    setVoiceTypingMessage("Finishing your transcript…")
    releaseDictationAudio()
    socket.send(JSON.stringify({ type: "dictation.stop" }))
  }, [cancelVoiceTyping, releaseDictationAudio])

  const startDictationAudio = async (socket: WebSocket) => {
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof AudioContext === "undefined") {
        throw new Error("This browser does not provide microphone audio capture.")
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      })
      if (dictationSocketRef.current !== socket || socket.readyState !== WebSocket.OPEN) {
        for (const track of stream.getTracks()) track.stop()
        return
      }

      dictationStreamRef.current = stream
      const audioContext = new AudioContext()
      dictationAudioContextRef.current = audioContext
      const moduleUrl = URL.createObjectURL(
        new Blob([DICTATION_PCM_WORKLET_SOURCE], { type: "text/javascript" }),
      )
      dictationModuleUrlRef.current = moduleUrl
      await audioContext.audioWorklet.addModule(moduleUrl)

      if (dictationSocketRef.current !== socket || socket.readyState !== WebSocket.OPEN) {
        releaseDictationAudio()
        return
      }

      const source = audioContext.createMediaStreamSource(stream)
      const worklet = new AudioWorkletNode(audioContext, "nova-dictation-pcm", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      })
      const muteGain = audioContext.createGain()
      muteGain.gain.value = 0
      worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (
          dictationSocketRef.current === socket
          && socket.readyState === WebSocket.OPEN
          && !dictationFinalizingRef.current
          && event.data instanceof ArrayBuffer
        ) {
          if (socket.bufferedAmount < 256_000) socket.send(event.data)
        }
      }

      source.connect(worklet)
      worklet.connect(muteGain)
      muteGain.connect(audioContext.destination)
      dictationSourceRef.current = source
      dictationWorkletRef.current = worklet
      dictationMuteGainRef.current = muteGain
      await audioContext.resume()
      setVoiceTypingMessage("Listening… speak naturally. Click the mic to finish and keep the text here.")
    } catch (captureError) {
      cancelVoiceTyping()
      const errorName = captureError instanceof DOMException ? captureError.name : ""
      setVoiceTypingMessage(
        errorName === "NotAllowedError" || errorName === "SecurityError"
          ? "Microphone access is blocked. Allow microphone access for NOVA in Opera site settings, then try again."
          : errorName === "NotFoundError"
            ? "No microphone was detected. Check your microphone connection."
            : captureError instanceof Error
              ? captureError.message
              : "Could not start microphone capture. Check permissions and try again.",
      )
    }
  }

  const toggleVoiceTyping = () => {
    if (voiceFinalizing) return
    setKeyboardTyping(false)
    if (voiceTyping) {
      finishVoiceTyping()
      textareaRef.current?.focus()
      return
    }
    if (dictationSocketRef.current) {
      cancelVoiceTyping()
    }

    const token = getAccessToken()
    if (!token) {
      setVoiceTypingMessage("Your NOVA session expired. Sign in again and retry voice typing.")
      return
    }

    voiceDraftPrefixRef.current = draft
    confirmedTranscriptRef.current = ""
    partialTranscriptRef.current = ""
    dictationFinalizingRef.current = false
    setVoiceTypingMessage("Connecting to NOVA speech recognition…")
    setVoiceTyping(true)

    let socket: WebSocket
    try {
      socket = new WebSocket(buildDictationWebSocketUrl())
      socket.binaryType = "arraybuffer"
    } catch (connectError) {
      setVoiceTyping(false)
      setVoiceTypingMessage(
        connectError instanceof Error ? connectError.message : "Could not connect to NOVA speech recognition.",
      )
      return
    }

    dictationSocketRef.current = socket
    socket.onopen = () => {
      if (dictationSocketRef.current !== socket) return
      socket.send(JSON.stringify({ type: "session.authenticate", access_token: token }))
    }

    socket.onmessage = (event: MessageEvent<string>) => {
      if (dictationSocketRef.current !== socket || typeof event.data !== "string") return
      let payload: DictationSocketMessage
      try {
        payload = JSON.parse(event.data) as DictationSocketMessage
      } catch {
        return
      }

      if (payload.type === "dictation.ready") {
        void startDictationAudio(socket)
        return
      }

      if (payload.type === "dictation.transcript" && payload.event?.text) {
        const transcript = payload.event.text.trim()
        if (!transcript) return
        if (payload.event.type === "transcript.final") {
          confirmedTranscriptRef.current = mergeDictationTranscript(
            confirmedTranscriptRef.current,
            transcript,
          )
          partialTranscriptRef.current = ""
        } else if (payload.event.type === "transcript.partial") {
          partialTranscriptRef.current = transcript
        }

        const heard = mergeDictationTranscript(
          confirmedTranscriptRef.current,
          partialTranscriptRef.current,
        )
        if (heard) {
          const prefix = voiceDraftPrefixRef.current
          const separator = prefix && !/\s$/.test(prefix) ? " " : ""
          setDraft(`${prefix}${separator}${heard}`)
        }
        return
      }

      if (payload.type === "dictation.final") {
        const finalText = payload.text?.trim()
        if (finalText) {
          const prefix = voiceDraftPrefixRef.current
          const separator = prefix && !/\s$/.test(prefix) ? " " : ""
          setDraft(`${prefix}${separator}${finalText}`)
        }
        dictationSocketRef.current = null
        dictationFinalizingRef.current = false
        releaseDictationAudio()
        socket.close()
        setVoiceTyping(false)
        setVoiceFinalizing(false)
        setVoiceTypingMessage(finalText
          ? "Transcript ready. Review it, then press Send."
          : "I couldn't hear any words. Try speaking a little closer to the microphone.")
        textareaRef.current?.focus()
        return
      }

      if (payload.type === "error") {
        dictationSocketRef.current = null
        dictationFinalizingRef.current = false
        releaseDictationAudio()
        socket.close()
        setVoiceTyping(false)
        setVoiceFinalizing(false)
        setVoiceTypingMessage(payload.message ?? "NOVA speech recognition failed. Please try again.")
      }
    }

    socket.onerror = () => {
      if (dictationSocketRef.current !== socket) return
      cancelVoiceTyping()
      setVoiceTypingMessage("NOVA dictation could not connect. Check that NOVA's backend and speech service are running.")
    }

    socket.onclose = () => {
      if (dictationSocketRef.current !== socket) return
      dictationSocketRef.current = null
      releaseDictationAudio()
      dictationFinalizingRef.current = false
      setVoiceTyping(false)
      setVoiceFinalizing(false)
      setVoiceTypingMessage("Dictation connection closed. Click the mic to try again.")
    }
  }

  useEffect(() => () => {
    const socket = dictationSocketRef.current
    dictationSocketRef.current = null
    releaseDictationAudio()
    if (socket && socket.readyState !== WebSocket.CLOSED) {
      try {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "dictation.cancel" }))
        }
        socket.close()
      } catch {
        // Browser teardown already owns the closing connection.
      }
    }
  }, [releaseDictationAudio])

  const loadMessages = useCallback(async (id: number) => {
    const requestId = messageLoadRequestRef.current + 1
    messageLoadRequestRef.current = requestId

    setLoadingMessages(true)
    setError(null)
    setErrorAction(null)
    setAssistantMeta(null)
    setConfirmationNotice(null)

    try {
      const result = await getConversationMessages(id)
      if (messageLoadRequestRef.current !== requestId) return

      shouldAutoScrollRef.current = true
      setShowScrollToBottom(false)
      setMessages(result.messages)

      try {
        const snapshot = await getConversationState(id)
        if (messageLoadRequestRef.current !== requestId) return
        setConversationState(snapshot)
      } catch {
        if (messageLoadRequestRef.current !== requestId) return
        setConversationState(null)
      }
    } catch (err) {
      if (messageLoadRequestRef.current !== requestId) return
      setMessages([])
      setConversationState(null)
      setError(formatApiError(err, "NOVA could not load this conversation."))
    } finally {
      if (messageLoadRequestRef.current === requestId) {
        setLoadingMessages(false)
      }
    }
  }, [])

  const refreshConversations = useCallback(async () => {
    const result = await getConversations()
    setConversations(result)
    return result
  }, [])

  useEffect(() => {
    const initialize = async () => {
      setLoading(true)
      setError(null)
      try {
        const result = await refreshConversations()
        if (result.length === 0) {
          setActiveId(null)
          setMessages([])
          return
        }

        const selected = result[0]
        setActiveId(selected.id)
        await loadMessages(selected.id)
      } catch (err) {
        setError(formatApiError(err, "NOVA could not load your conversations."))
      } finally {
        setLoading(false)
      }
    }

    void initialize()
  }, [loadMessages, refreshConversations])

  const updateMessageScrollState = useCallback(() => {
    const node = messageScrollRef.current
    if (!node) return

    const distanceFromBottom =
      node.scrollHeight - node.scrollTop - node.clientHeight
    const nearBottom = distanceFromBottom <= 96

    shouldAutoScrollRef.current = nearBottom
    setShowScrollToBottom(!nearBottom)
  }, [])

  const scrollMessagesToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const node = messageScrollRef.current
    if (!node) return

    shouldAutoScrollRef.current = true
    node.scrollTo({
      top: node.scrollHeight,
      behavior,
    })
    setShowScrollToBottom(false)
  }, [])

  useEffect(() => {
    if (!shouldAutoScrollRef.current) {
      updateMessageScrollState()
      return
    }

    const node = messageScrollRef.current
    if (!node) return

    requestAnimationFrame(() => {
      node.scrollTo({
        top: node.scrollHeight,
        behavior: "smooth",
      })
      updateMessageScrollState()
    })
  }, [messages, sending, updateMessageScrollState])

  useEffect(() => {
    const node = textareaRef.current
    if (!node) return

    node.style.height = "auto"
    node.style.height = `${Math.min(node.scrollHeight, 180)}px`
  }, [draft])

  const clearError = () => {
    setError(null)
    setErrorAction(null)
  }

  const newConversation = async () => {
    if (
      sending ||
      savingId !== null ||
      deletingId !== null ||
      creatingConversation
    ) return

    cancelVoiceTyping()
    setCreatingConversation(true)
    // Invalidate any post-response state refresh still running for the old thread.
    messageLoadRequestRef.current += 1
    setEditingId(null)
    setRetryPayload(null)
    clearError()
    setAssistantMeta(null)
    setConfirmationNotice(null)

    try {
      const result = await createConversation()
      setActiveId(result.id)
      shouldAutoScrollRef.current = true
      setShowScrollToBottom(false)
      setMessages([])
      setDraft("")
      setKeyboardTyping(false)
      await refreshConversations()

      try {
        setConversationState(await getConversationState(result.id))
      } catch {
        setConversationState(null)
      }

      textareaRef.current?.focus()
    } catch (err) {
      setError(formatApiError(err, "NOVA could not create a new conversation."))
      setErrorAction(null)
    } finally {
      setCreatingConversation(false)
    }
  }

  const selectConversation = async (id: number) => {
    if (sending || savingId !== null || deletingId !== null || creatingConversation || id === activeId) return
    cancelVoiceTyping()
    setActiveId(id)
    setEditingId(null)
    setRetryPayload(null)
    clearError()
    await loadMessages(id)
  }

  const sendMessage = async (payload: RetryPayload, optimistic: boolean) => {
    setError(null)
    setErrorAction(null)
    setConfirmationNotice(null)
    setAssistantMeta(null)
    setSending(true)

    if (optimistic) {
      setMessages((current) => [...current, { role: "user", content: payload.message }])
    }

    try {
      const result = await sendChatMessage(payload)
      setActiveId(result.conversation_id)
      setMessages((current) => [...current, { role: "assistant", content: result.response }])
      setAssistantMeta(result)
      setRetryPayload(null)

      // The user-visible turn is complete as soon as /chat returns. Do not keep
      // the composer disabled while ancillary list/state refreshes are pending.
      setSending(false)

      const stateRequestId = messageLoadRequestRef.current + 1
      messageLoadRequestRef.current = stateRequestId

      void refreshConversations().catch((err: unknown) => {
        console.warn("Conversation list refresh after chat response failed.", err)
      })
      void getConversationState(result.conversation_id)
        .then((snapshot) => {
          if (messageLoadRequestRef.current === stateRequestId) {
            setConversationState(snapshot)
          }
        })
        .catch(() => {
          if (messageLoadRequestRef.current === stateRequestId) {
            setConversationState(null)
          }
        })
    } catch (err) {
      setRetryPayload(payload)
      setError(formatApiError(err, "NOVA could not complete that message."))
      setErrorAction("retry")
    } finally {
      setSending(false)
    }
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    cancelVoiceTyping()
    const message = draft.trim()
    if (!message || sending) return

    setDraft("")
    setKeyboardTyping(false)
    textareaRef.current?.focus()

    await sendMessage(
      {
        message,
        conversationId: activeId,
        idempotencyKey: requestId(),
      },
      true,
    )
  }

  const retryLastMessage = async () => {
    if (!retryPayload || sending) return
    await sendMessage(retryPayload, false)
  }

  const beginRename = (conversation: Conversation) => {
    if (sending || savingId !== null || deletingId !== null) return
    setEditingId(conversation.id)
    setEditingTitle(conversation.title || "New Conversation")
    clearError()
  }

  const cancelRename = () => {
    if (savingId !== null) return
    setEditingId(null)
    setEditingTitle("")
  }

  const saveRename = async (event: FormEvent<HTMLFormElement>, conversationId: number) => {
    event.preventDefault()
    const title = editingTitle.trim()

    if (!title) {
      setError("Conversation title cannot be empty.")
      setErrorAction(null)
      return
    }

    setSavingId(conversationId)
    clearError()

    try {
      await updateConversationTitle(conversationId, title)
      await refreshConversations()
      setEditingId(null)
      setEditingTitle("")
    } catch (err) {
      setError(formatApiError(err, "NOVA could not rename this conversation."))
      setErrorAction(null)
    } finally {
      setSavingId(null)
    }
  }

  const confirmDelete = async () => {
    if (deleteId === null || deletingId !== null) return

    const targetId = deleteId
    setDeletingId(targetId)
    clearError()

    try {
      await deleteConversation(targetId)
      const result = await refreshConversations()

      setDeleteId(null)
      setEditingId(null)

      if (activeId === targetId) {
        if (result.length === 0) {
          setActiveId(null)
          setMessages([])
        } else {
          setActiveId(result[0].id)
          await loadMessages(result[0].id)
        }
      }
    } catch (err) {
      setError(formatApiError(err, "NOVA could not delete this conversation."))
      setErrorAction(null)
    } finally {
      setDeletingId(null)
    }
  }

  const active = conversations.find((item) => item.id === activeId)
  const deleteTarget = conversations.find((item) => item.id === deleteId)
  const handleConfirmation = async (
    confirmationId: number,
    action: "approve" | "reject",
  ) => {
    if (confirmationBusy !== null) return

    setConfirmationBusy(action)
    setConfirmationNotice(null)
    setError(null)
    setErrorAction(null)

    try {
      if (action === "approve") {
        const result = await approveAndExecuteConfirmation(confirmationId)
        setAssistantMeta((current) =>
          current
            ? {
                ...current,
                confirmation: {
                  ...(current.confirmation ?? {}),
                  status: result.status,
                },
                tool_result: result.tool_result,
                workflow_result: result.workflow_result,
              }
            : current,
        )
        setConfirmationNotice(
          result.success
            ? "The requested action completed successfully."
            : result.error || "The requested action did not complete.",
        )
      } else {
        const result = await rejectConfirmation(confirmationId)
        setAssistantMeta((current) =>
          current
            ? {
                ...current,
                confirmation: {
                  ...(current.confirmation ?? {}),
                  status: result.status,
                },
              }
            : current,
        )
        setConfirmationNotice("The requested action was rejected.")
      }
    } catch (err) {
      setError(formatApiError(err, "NOVA could not update this approval."))
      setErrorAction(null)
    } finally {
      setConfirmationBusy(null)
    }
  }


  return (
    <div className="conversation-shell">
      <aside className="conversation-sidebar">
        <div className="conversation-sidebar-header">
          <div>
            <div className="section-kicker">CONVERSATIONS</div>
            <h1>Your threads</h1>
          </div>
          <button
            className="icon-action"
            type="button"
            aria-label="New conversation"
            onClick={newConversation}
            disabled={sending || savingId !== null || deletingId !== null}
          >
            <Icon name="plus" size={18} />
          </button>
        </div>

        <button
          className="conversation-new-button"
          type="button"
          onClick={newConversation}
          disabled={sending || savingId !== null || deletingId !== null}
        >
          <Icon name="plus" size={16} />
          New conversation
        </button>

        <div className="conversation-list" aria-label="Conversations">
          {loading ? (
            <div className="conversation-list-state">
              <div />
              <div />
              <div />
            </div>
          ) : conversations.length === 0 ? (
            <div className="conversation-list-empty">
              No saved conversations yet.
              <br />
              Your first message will start one.
            </div>
          ) : (
            conversations.map((conversation) => {
              const isEditing = conversation.id === editingId
              const isSaving = conversation.id === savingId
              const isDeleting = conversation.id === deletingId

              return (
                <div
                  className={
                    conversation.id === activeId
                      ? "conversation-list-item active"
                      : "conversation-list-item"
                  }
                  key={conversation.id}
                >
                  {isEditing ? (
                    <form
                      className="conversation-rename-form"
                      onSubmit={(event) => void saveRename(event, conversation.id)}
                    >
                      <input
                        value={editingTitle}
                        onChange={(event) => setEditingTitle(event.target.value)}
                        maxLength={200}
                        aria-label="Conversation title"
                        autoFocus
                        disabled={isSaving}
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            event.preventDefault()
                            cancelRename()
                          }
                        }}
                      />
                      <button
                        className="conversation-item-action save"
                        type="submit"
                        aria-label="Save conversation title"
                        disabled={isSaving || !editingTitle.trim()}
                      >
                        <Icon name="check" size={14} />
                      </button>
                      <button
                        className="conversation-item-action cancel"
                        type="button"
                        aria-label="Cancel rename"
                        onClick={cancelRename}
                        disabled={isSaving}
                      >
                        ×
                      </button>
                    </form>
                  ) : (
                    <>
                      <button
                        className="conversation-list-select"
                        type="button"
                        onClick={() => void selectConversation(conversation.id)}
                        disabled={sending || savingId !== null || deletingId !== null}
                      >
                        <span>{conversation.title || "New Conversation"}</span>
                        <small>{formatTime(conversation.updated_at)}</small>
                      </button>
                      <div className="conversation-item-actions" aria-label="Conversation actions">
                        <button
                          className="conversation-item-action"
                          type="button"
                          aria-label={`Rename ${conversation.title || "conversation"}`}
                          title="Rename conversation"
                          onClick={() => beginRename(conversation)}
                          disabled={sending || savingId !== null || deletingId !== null}
                        >
                          <Icon name="edit" size={14} />
                        </button>
                        <button
                          className="conversation-item-action danger"
                          type="button"
                          aria-label={`Delete ${conversation.title || "conversation"}`}
                          title="Delete conversation"
                          onClick={() => {
                            setDeleteId(conversation.id)
                            clearError()
                          }}
                          disabled={sending || savingId !== null || deletingId !== null}
                        >
                          <Icon name="trash" size={14} />
                        </button>
                      </div>
                    </>
                  )}
                  {isDeleting && <div className="conversation-item-progress" aria-hidden="true" />}
                </div>
              )
            })
          )}
        </div>
      </aside>

      <section className="conversation-panel">
        <header className="conversation-header">
          <div>
            <div className="section-kicker">NOVA</div>
            <h2>{active?.title || "New conversation"}</h2>
          </div>
          <div className="conversation-state" aria-live="polite">
            <span className="connection-dot" />
            {voiceTyping
              ? voiceTypingMessage?.startsWith("Listening")
                ? "Listening"
                : "Connecting"
              : voiceFinalizing
                ? "Transcribing"
                : sending
                  ? "Thinking"
                  : keyboardTyping
                    ? "Typing"
                    : conversationState
                      ? formatConversationState(conversationState)
                    : "Ready"}
          </div>
        </header>

        <div
          ref={messageScrollRef}
          className="message-scroll-area"
          onScroll={updateMessageScrollState}
        >
          {loadingMessages ? (
            <div className="conversation-empty">
              <div className="loading-pulse" />
              <span>Opening conversation…</span>
            </div>
          ) : messages.length === 0 ? (
            <div className="conversation-empty">
              <div className="conversation-empty-orb">
                <Icon name="spark" size={24} />
              </div>
              <div className="section-kicker">START WITH NOVA</div>
              <h3>What should we work on?</h3>
              <p>
                Ask a question, plan something, research a topic, or tell NOVA what you need handled.
              </p>
            </div>
          ) : (
            <div className="message-stack" aria-live="polite">
              {messages.map((message, index) => (
                <MessageBubble key={`${message.role}-${index}`} message={message} />
              ))}
              {sending && (
                <div className="message-row assistant">
                  <div className="assistant-avatar">
                    <Icon name="spark" size={14} />
                  </div>
                  <div className="message-bubble assistant">
                    <span>NOVA is thinking…</span>
                    <span className="thinking-dots">
                      <i />
                      <i />
                      <i />
                    </span>
                  </div>
                </div>
              )}
              {assistantMeta && (
                <ConversationResponseDetails
                  response={assistantMeta}
                  confirmationNotice={confirmationNotice}
                  confirmationBusy={confirmationBusy}
                  onConfirmation={handleConfirmation}
                />
              )}
            </div>
          )}

          {showScrollToBottom && messages.length > 0 && (
            <button
              className="conversation-scroll-to-bottom"
              type="button"
              aria-label="Scroll to latest message"
              title="Scroll to latest message"
              onClick={() => scrollMessagesToBottom()}
            >
              <Icon name="arrow" size={16} />
            </button>
          )}
        </div>

        {error && (
          <div className="conversation-error" role="alert">
            <span>{error}</span>
            {errorAction === "retry" && retryPayload && (
              <button
                className="conversation-retry"
                type="button"
                onClick={() => void retryLastMessage()}
                disabled={sending}
              >
                Retry
              </button>
            )}
          </div>
        )}

        <form className="conversation-composer" onSubmit={submit}>
          <button
            className={`composer-voice${voiceTyping ? " is-listening" : ""}`}
            type="button"
            aria-label={voiceFinalizing ? "Finishing voice transcription" : voiceTyping ? "Finish voice typing" : "Start voice typing"}
            title={voiceFinalizing ? "Finishing transcript…" : voiceTyping ? "Finish dictation" : "Dictate message"}
            aria-pressed={voiceTyping}
            onClick={toggleVoiceTyping}
            disabled={sending || voiceFinalizing}
          >
            <Icon name="mic" size={18} />
          </button>
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(event) => {
              const nextDraft = event.target.value
              setDraft(nextDraft)
              setKeyboardTyping(Boolean(nextDraft.trim()))
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
            placeholder="Message NOVA…"
            rows={1}
            maxLength={12000}
            aria-label="Message NOVA"
            disabled={sending}
          />
          <button
            className="composer-send"
            type="submit"
            aria-label="Send message"
            disabled={!draft.trim() || sending}
          >
            <Icon name="arrow" size={18} />
          </button>
        </form>
        <div className="composer-hint" aria-live="polite">
          {voiceTyping
            ? voiceTypingMessage ?? "Listening… speak naturally. Click the mic to finish."
            : voiceTypingMessage ?? "Enter to send · Shift + Enter for a new line"}
        </div>
      </section>

      {deleteTarget && (
        <div className="conversation-dialog-backdrop">
          <div
            className="conversation-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="conversation-delete-title"
          >
            <div className="section-kicker">DELETE CONVERSATION</div>
            <h3 id="conversation-delete-title">Remove this thread?</h3>
            <p>
              “{deleteTarget.title || "New Conversation"}” will be permanently deleted.
            </p>
            <div className="conversation-dialog-actions">
              <button
                className="secondary-action"
                type="button"
                onClick={() => setDeleteId(null)}
                disabled={deletingId !== null}
              >
                Cancel
              </button>
              <button
                className="danger-action"
                type="button"
                onClick={() => void confirmDelete()}
                disabled={deletingId !== null}
              >
                {deletingId !== null ? "Deleting…" : "Delete conversation"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function formatConversationState(snapshot: ConversationState): string {
  const state = snapshot.state.trim().toLowerCase()
  // Backend should_listen describes assistant capability, not an active
  // microphone on the Conversation surface. Dictation UI owns that state.
  if (snapshot.should_listen || state === "listening") return "Ready"
  if (state.includes("process") || state.includes("think") || state === "running") return "Thinking"
  if (state.includes("speak")) return "Speaking"
  if (state.includes("error") || state.includes("fail")) return "Needs attention"
  return "Ready"
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function textValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null
}

function sourceUrl(value: unknown): string | null {
  const url = textValue(value)
  return url && /^https?:\/\//i.test(url) ? url : null
}

function formatRecipientPreview(value: unknown, fallback: string): string {
  if (typeof value === "string") return value.trim() || fallback
  if (Array.isArray(value)) {
    const recipients = value.filter(
      (item): item is string => typeof item === "string" && item.trim().length > 0,
    )
    return recipients.join(", ") || fallback
  }
  return fallback
}

function payloadSummary(value: unknown): string {
  if (!isRecord(value)) return "Completed"
  for (const key of ["message", "summary", "title", "status", "action", "result"]) {
    const candidate = textValue(value[key])
    if (candidate) return candidate
  }
  const entries = Object.entries(value)
    .filter(([, item]) => ["string", "number", "boolean"].includes(typeof item))
    .slice(0, 3)
  if (entries.length === 0) return "Completed"
  return entries.map(([key, item]) => key + ": " + String(item)).join(" · ")
}

function sourceTitle(source: Record<string, unknown>, index: number): string {
  return textValue(source.title) || textValue(source.name) || textValue(source.source) || "Source " + (index + 1)
}

function sourceDescription(source: Record<string, unknown>): string | null {
  return textValue(source.snippet) || textValue(source.content) || textValue(source.description)
}

function ConversationResponseDetails({
  response,
  confirmationNotice,
  confirmationBusy,
  onConfirmation,
}: {
  response: ChatResponse
  confirmationNotice: string | null
  confirmationBusy: "approve" | "reject" | null
  onConfirmation: (confirmationId: number, action: "approve" | "reject") => void
}) {
  const rawConfirmation = isRecord(response.confirmation) ? response.confirmation : null
  const rawConfirmationId = rawConfirmation ? Number(rawConfirmation.id) : NaN
  const confirmation =
    rawConfirmation &&
    Number.isInteger(rawConfirmationId) &&
    rawConfirmationId > 0 &&
    textValue(rawConfirmation.status)
      ? rawConfirmation
      : null
  const confirmationId = confirmation ? Number(confirmation.id) : NaN
  const confirmationStatus = confirmation
    ? String(confirmation.status).toLowerCase()
    : null
  const emailPreview =
    confirmation &&
    isRecord(confirmation.preview) &&
    textValue(confirmation.preview.kind) === "email"
      ? confirmation.preview
      : null
  const sources: Array<Record<string, unknown>> = [
    ...(response.web_sources ?? []).map((source) => ({ ...source, kind: "Web" })),
    ...(response.knowledge_sources ?? []).map((source) => ({ ...source, kind: "Knowledge" })),
  ]
  const hasActionResult =
    isRecord(response.tool_result) &&
    (textValue(response.tool_result.tool) !== null ||
      textValue(response.tool_result.action) !== null ||
      (response.tool_result.result !== null && response.tool_result.result !== undefined) ||
      textValue(response.tool_result.error) !== null)
  const hasWorkflowResult =
    isRecord(response.workflow_result) &&
    (textValue(response.workflow_result.status) !== null ||
      (response.workflow_result.workflow_id !== null && response.workflow_result.workflow_id !== undefined) ||
      (response.workflow_result.scheduled_at !== null && response.workflow_result.scheduled_at !== undefined) ||
      (Array.isArray(response.workflow_result.steps) && response.workflow_result.steps.length > 0) ||
      textValue(response.workflow_result.error) !== null)
  const resultBlocks = [
    hasActionResult ? { label: "Action", value: response.tool_result as Record<string, unknown> } : null,
    hasWorkflowResult ? { label: "Workflow", value: response.workflow_result as Record<string, unknown> } : null,
    response.memory_action ? { label: "Memory", value: response.memory_action } : null,
  ].filter(Boolean) as Array<{ label: string; value: Record<string, unknown> }>
  if (!confirmation && resultBlocks.length === 0 && sources.length === 0 && !confirmationNotice) return null
  const canActOnConfirmation = Number.isInteger(confirmationId) && confirmationStatus === "pending"
  return (
    <div className="conversation-response-details">
      {confirmation && (
        <section className="conversation-detail-card approval">
          <div className="conversation-detail-heading">
            <div>
              <div className="section-kicker">APPROVAL REQUIRED</div>
              <h4>{textValue(confirmation.action) || "Confirm this action"}</h4>
            </div>
            <span className="conversation-detail-status">{confirmationStatus || "pending"}</span>
          </div>
          {textValue(confirmation.reason) && <p>{textValue(confirmation.reason)}</p>}
          {emailPreview && (
            <div className="conversation-email-preview" aria-label="Email draft preview">
              <div className="conversation-email-preview-label">EMAIL DRAFT · REVIEW BEFORE SENDING</div>
              <dl className="conversation-email-preview-fields">
                <div>
                  <dt>To</dt>
                  <dd>{formatRecipientPreview(emailPreview.to, "Not specified")}</dd>
                </div>
                {emailPreview.cc !== undefined && emailPreview.cc !== null && emailPreview.cc !== "" && (
                  <div>
                    <dt>CC</dt>
                    <dd>{formatRecipientPreview(emailPreview.cc, "—")}</dd>
                  </div>
                )}
                {emailPreview.bcc !== undefined && emailPreview.bcc !== null && emailPreview.bcc !== "" && (
                  <div>
                    <dt>BCC</dt>
                    <dd>{formatRecipientPreview(emailPreview.bcc, "—")}</dd>
                  </div>
                )}
                <div>
                  <dt>Subject</dt>
                  <dd>{textValue(emailPreview.subject) || "(No subject)"}</dd>
                </div>
              </dl>
              <div className="conversation-email-preview-label">MESSAGE</div>
              <div className="conversation-email-preview-body">
                {typeof emailPreview.body === "string" ? emailPreview.body : "(Empty draft)"}
              </div>
            </div>
          )}
          {canActOnConfirmation && (
            <div className="conversation-detail-actions">
              <button className="secondary-action" type="button" onClick={() => onConfirmation(confirmationId, "reject")} disabled={confirmationBusy !== null}>
                {confirmationBusy === "reject" ? "Rejecting…" : "Reject"}
              </button>
              <button className="primary-action" type="button" onClick={() => onConfirmation(confirmationId, "approve")} disabled={confirmationBusy !== null}>
                {confirmationBusy === "approve"
                  ? (emailPreview ? "Sending…" : "Approving…")
                  : (emailPreview ? "Send email" : "Approve & execute")}
              </button>
            </div>
          )}
        </section>
      )}
      {resultBlocks.map((block) => (
        <section className="conversation-detail-card" key={block.label}>
          <div className="conversation-detail-heading">
            <div><div className="section-kicker">{block.label}</div><h4>{payloadSummary(block.value)}</h4></div>
          </div>
        </section>
      ))}
      {confirmationNotice && <div className="conversation-detail-notice" role="status">{confirmationNotice}</div>}
      {sources.length > 0 && (
        <section className="conversation-detail-card sources">
          <div className="conversation-detail-heading">
            <div><div className="section-kicker">SOURCES</div><h4>What informed this response</h4></div>
            <span className="conversation-detail-status">{sources.length}</span>
          </div>
          <div className="conversation-source-list">
            {sources.slice(0, 8).map((source, index) => {
              const href = sourceUrl(source.url) || sourceUrl(source.link) || sourceUrl(source.source)
              return (
                <article className="conversation-source-item" key={sourceTitle(source, index) + "-" + index}>
                  <div>
                    <div className="conversation-source-kind">{String(source.kind)}</div>
                    <strong>{sourceTitle(source, index)}</strong>
                    {sourceDescription(source) && <p>{sourceDescription(source)}</p>}
                  </div>
                  {href && <a href={href} target="_blank" rel="noreferrer">Open</a>}
                </article>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}

function MessageBubble({ message }: { message: ConversationMessage }) {
  if (message.role === "system") return <div className="message-system">{message.content}</div>
  if (message.role === "user") {
    return (
      <div className="message-row user">
        <div className="message-bubble user">{message.content}</div>
      </div>
    )
  }

  return (
    <div className="message-row assistant">
      <div className="assistant-avatar">
        <Icon name="spark" size={14} />
      </div>
      <div className="message-bubble assistant">{message.content}</div>
    </div>
  )
}
