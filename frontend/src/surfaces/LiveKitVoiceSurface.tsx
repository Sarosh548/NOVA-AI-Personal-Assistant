import { useCallback, useEffect, useRef, useState } from "react"
import {
  Room,
  RoomEvent,
  Track,
  type Participant,
  type TranscriptionSegment,
} from "livekit-client"

import { ApiRequestError, apiRequestWithRefresh } from "../api/client"
import {
  approveAndExecuteConfirmation,
  rejectConfirmation,
  updateEmailConfirmationRecipient,
} from "../api/workspace"
import { Icon } from "../components/Icon"

const ACTIVE_CONVERSATION_STORAGE_KEY = "nova_active_conversation_id"

function getStoredConversationId(): number | null {
  try {
    const stored = window.sessionStorage.getItem(ACTIVE_CONVERSATION_STORAGE_KEY)
    const parsed = stored ? Number(stored) : NaN
    return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
  } catch {
    return null
  }
}

function storeConversationId(id: number | null): void {
  try {
    if (id === null) {
      window.sessionStorage.removeItem(ACTIVE_CONVERSATION_STORAGE_KEY)
    } else {
      window.sessionStorage.setItem(ACTIVE_CONVERSATION_STORAGE_KEY, String(id))
    }
  } catch {
    // The active voice session still works when storage is blocked.
  }
}


type VoicePhase = "connecting" | "listening" | "thinking" | "speaking" | "disconnected"

type LiveKitTokenResponse = {
  server_url: string
  token: string
  room_name: string
  conversation_id: number
  participant_identity: string
}

type TranscriptSpeaker = "user" | "assistant"

type TranscriptMessage = {
  id: string
  speaker: TranscriptSpeaker
  text: string
  final: boolean
  updatedAt: number
}

type ConversationCreated = { id: number }
type VoiceWireEvent = {
  type?: string
  speaker?: TranscriptSpeaker
  id?: string
  text?: string
  final?: boolean
  state?: string
  confirmation_id?: number | string
  status?: string
  tool?: string
  action?: string
  reason?: string
  preview?: Record<string, unknown>
  recipient_email?: string
  ok?: boolean
  message?: string
}

type VoiceEmailReview = {
  confirmationId: number
  reason: string | null
  preview: Record<string, unknown>
}

function formatEmailPreviewValue(value: unknown, fallback: string): string {
  if (typeof value === "string") return value.trim() || fallback
  if (Array.isArray(value)) {
    const recipients = value.filter(
      (item): item is string => typeof item === "string" && item.trim().length > 0,
    )
    return recipients.join(", ") || fallback
  }
  return fallback
}

function createMessageId(speaker: TranscriptSpeaker): string {
  return `${speaker}-${crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`}`
}

function normalizeTranscriptForDedupe(text: string): string {
  return text.normalize("NFKC").toLowerCase().replace(/[.,:;!?\'\"()\-]/g, " ").replace(/\s+/g, " ").trim()
}

function renderTranscriptText(text: string) {
  const parts = text.split(/(https?:\/\/[^\s<>]+)/g)
  return parts.map((part, index) => (
    /^https?:\/\//i.test(part)
      ? (
          <a
            key={`source-link-${index}`}
            href={part}
            target="_blank"
            rel="noopener noreferrer"
            className="voice-source-link"
          >
            {part}
          </a>
        )
      : part
  ))
}

function mapAgentState(value: string | undefined): VoicePhase {
  switch (value) {
    case "thinking":
    case "initializing":
      return "thinking"
    case "speaking":
      return "speaking"
    case "listening":
    case "idle":
      return "listening"
    case "disconnected":
    case "error":
      return "disconnected"
    default:
      return "listening"
  }
}

export function LiveKitVoiceSurface({
  onOpenConversation,
}: {
  onOpenConversation: () => void
}) {
  const [phase, setPhase] = useState<VoicePhase>("disconnected")
  const [connected, setConnected] = useState(false)
  const [needsAudioTap, setNeedsAudioTap] = useState(false)
  const [creatingConversation, setCreatingConversation] = useState(false)
  const [messages, setMessages] = useState<TranscriptMessage[]>([])
  const [emailReview, setEmailReview] = useState<VoiceEmailReview | null>(null)
  const [emailReviewBusy, setEmailReviewBusy] = useState<"send" | "reject" | null>(null)
  const [emailReviewNotice, setEmailReviewNotice] = useState<string | null>(null)
  const [reviewRecipientDraft, setReviewRecipientDraft] = useState("")
  const [reviewRecipientBusy, setReviewRecipientBusy] = useState(false)
  const [showTypedEmailEntry, setShowTypedEmailEntry] = useState(false)
  const [typedEmailDraft, setTypedEmailDraft] = useState("")
  const [typedEmailBusy, setTypedEmailBusy] = useState(false)
  const [typedEmailNotice, setTypedEmailNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [conversationId, setConversationId] = useState<number | null>(
    () => getStoredConversationId(),
  )
  const [reconnectKey, setReconnectKey] = useState(0)
  const [leaseSessionId, setLeaseSessionId] = useState<string | null>(null)

  const roomRef = useRef<Room | null>(null)
  const leaseSessionIdRef = useRef<string | null>(null)
  const transcriptPanelRef = useRef<HTMLDivElement | null>(null)
  const audioSinkRef = useRef<HTMLDivElement | null>(null)
  const connectingRef = useRef(false)
  const mountedRef = useRef(true)
  const agentJoinedRef = useRef(false)
  const agentJoinTimeoutRef = useRef<number | null>(null)
  const responseWatchdogRef = useRef<number | null>(null)
  const agentSilenceFallbackRef = useRef<number | null>(null)
  const heardChimeRef = useRef(false)
  const firstAutomaticRecoveryAtRef = useRef(0)
  const automaticRecoveryAttemptsRef = useRef(0)
  const recoveryInProgressRef = useRef(false)
  const recoveryTimerRef = useRef<number | null>(null)
  const cancelRecoveryWaitRef = useRef<(() => void) | null>(null)

  const clearResponseWatchdog = useCallback(() => {
    if (responseWatchdogRef.current !== null) {
      window.clearTimeout(responseWatchdogRef.current)
      responseWatchdogRef.current = null
    }
  }, [])

  const upsertTranscript = useCallback((
    speaker: TranscriptSpeaker,
    id: string,
    text: string,
    final: boolean,
  ) => {
    const cleanedText = text.trim()
    if (!cleanedText) return
    const now = Date.now()
    setMessages((previous) => {
      const currentIndex = previous.findIndex((entry) => entry.id === id)
      if (currentIndex >= 0) {
        const next = previous.slice()
        next[currentIndex] = {
          ...next[currentIndex],
          speaker,
          text: cleanedText,
          final,
          updatedAt: now,
        }
        return next
      }

      // Native LiveKit transcription and NOVA's UI transcript event can use
      // different IDs for the same utterance. Reconcile exact text regardless
      // of which channel reports finality; otherwise a final UI event followed
      // by a non-final spoken-transcript segment creates a duplicate card.
      // The short window still permits the same sentence later in the session.
      const duplicateKey = normalizeTranscriptForDedupe(cleanedText)
      const duplicateIndex = previous.findIndex((entry) => {
        if (
          speaker !== "assistant"
          || entry.speaker !== speaker
          || now - entry.updatedAt > 60_000
        ) {
          return false
        }
        const existingKey = normalizeTranscriptForDedupe(entry.text)
        if (existingKey === duplicateKey) return true

        // Native LiveKit output can arrive as an incremental prefix of the
        // authenticated NOVA transcript (or the other way around). Reconcile
        // these variants into one card instead of reintroducing the old
        // double-transcript UI. Keep a minimum length to avoid merging generic
        // one-word replies such as "Yes" into unrelated spoken messages.
        const shorterLength = Math.min(existingKey.length, duplicateKey.length)
        return (
          shorterLength >= 6
          && (
            existingKey.startsWith(duplicateKey)
            || duplicateKey.startsWith(existingKey)
          )
        )
      })
      if (duplicateIndex >= 0) {
        const duplicate = previous[duplicateIndex]
        const existingKey = normalizeTranscriptForDedupe(duplicate.text)
        const nextText = duplicateKey.length > existingKey.length
          ? cleanedText
          : duplicate.text
        const next = previous.slice()
        next[duplicateIndex] = {
          ...duplicate,
          text: nextText,
          final: duplicate.final || final,
          updatedAt: now,
        }
        return next
      }

      return [
        ...previous,
        { id, speaker, text: cleanedText, final, updatedAt: now },
      ].slice(-40)
    })
  }, [])

  const playEntryChime = useCallback(async () => {
    if (heardChimeRef.current) return
    heardChimeRef.current = true
    try {
      const audioContext = new AudioContext()
      await audioContext.resume()
      const oscillator = audioContext.createOscillator()
      const gain = audioContext.createGain()
      oscillator.type = "sine"
      oscillator.frequency.setValueAtTime(660, audioContext.currentTime)
      oscillator.frequency.exponentialRampToValueAtTime(520, audioContext.currentTime + 0.11)
      gain.gain.setValueAtTime(0.0001, audioContext.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.035, audioContext.currentTime + 0.018)
      gain.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + 0.13)
      oscillator.connect(gain)
      gain.connect(audioContext.destination)
      oscillator.start()
      oscillator.stop(audioContext.currentTime + 0.14)
      window.setTimeout(() => void audioContext.close().catch(() => undefined), 350)
    } catch {
      // Browser autoplay policy may suppress the optional soft entry cue.
    }
  }, [])

  const releaseVoiceLease = useCallback(async (sessionId: string | null) => {
    if (!sessionId) return
    try {
      await apiRequestWithRefresh<{ released: boolean }>(
        "/voice/livekit/lease?session_id=" + encodeURIComponent(sessionId),
        { method: "DELETE" },
      )
    } catch {
      // The lease service also expires abandoned sessions after missed heartbeats.
    }
  }, [])

  const disconnectRoom = useCallback(async (options?: { preserveRecovery?: boolean }) => {
    if (recoveryTimerRef.current !== null) {
      window.clearTimeout(recoveryTimerRef.current)
      recoveryTimerRef.current = null
    }
    const cancelRecoveryWait = cancelRecoveryWaitRef.current
    cancelRecoveryWaitRef.current = null
    if (cancelRecoveryWait) cancelRecoveryWait()
    if (!options?.preserveRecovery) {
      recoveryInProgressRef.current = false
      firstAutomaticRecoveryAtRef.current = 0
      automaticRecoveryAttemptsRef.current = 0
    }
    clearResponseWatchdog()
    if (agentSilenceFallbackRef.current !== null) {
      window.clearTimeout(agentSilenceFallbackRef.current)
      agentSilenceFallbackRef.current = null
    }
    const room = roomRef.current
    const sessionId = leaseSessionIdRef.current
    roomRef.current = null
    leaseSessionIdRef.current = null
    setLeaseSessionId(null)
    void releaseVoiceLease(sessionId)
    agentJoinedRef.current = false
    if (agentJoinTimeoutRef.current !== null) {
      window.clearTimeout(agentJoinTimeoutRef.current)
      agentJoinTimeoutRef.current = null
    }
    setConnected(false)
    setNeedsAudioTap(false)
    if (room) {
      try {
        await room.disconnect()
      } catch {
        // The server or peer may already have closed the room.
      }
    }
    const audioSink = audioSinkRef.current
    if (audioSink) {
      for (const element of Array.from(audioSink.querySelectorAll("audio,video"))) {
        element.remove()
      }
    }
  }, [clearResponseWatchdog, releaseVoiceLease])

  const recoverAfterAgentDisconnect = useCallback(async () => {
    if (recoveryInProgressRef.current) return
    recoveryInProgressRef.current = true

    const now = Date.now()
    // Allow a small retry budget per incident, then stop and ask for a manual
    // reconnect. This handles transient DNS/WebSocket failures without spinning
    // forever or repeatedly creating Gemini/LiveKit sessions.
    if (
      !firstAutomaticRecoveryAtRef.current
      || now - firstAutomaticRecoveryAtRef.current > 90_000
    ) {
      firstAutomaticRecoveryAtRef.current = now
      automaticRecoveryAttemptsRef.current = 0
    }
    const attempt = automaticRecoveryAttemptsRef.current + 1
    automaticRecoveryAttemptsRef.current = attempt

    await disconnectRoom({ preserveRecovery: true })
    if (!mountedRef.current) {
      recoveryInProgressRef.current = false
      return
    }
    if (attempt > 3) {
      setPhase("disconnected")
      setError("NOVA's realtime model could not reconnect after 3 automatic attempts. Tap the orb to retry; your saved conversation is preserved.")
      recoveryInProgressRef.current = false
      return
    }

    const retryDelaysMs = [1_000, 2_500, 5_000] as const
    setPhase("connecting")
    setError(
      `The realtime model disconnected. Reconnecting (attempt ${attempt} of 3); your saved conversation is preserved.`,
    )
    const delayElapsed = await new Promise<boolean>((resolve) => {
      let settled = false
      let cancelWait: (() => void) | null = null
      const finish = (elapsed: boolean) => {
        if (settled) return
        settled = true
        if (recoveryTimerRef.current !== null) {
          window.clearTimeout(recoveryTimerRef.current)
          recoveryTimerRef.current = null
        }
        if (cancelRecoveryWaitRef.current === cancelWait) {
          cancelRecoveryWaitRef.current = null
        }
        resolve(elapsed)
      }
      recoveryTimerRef.current = window.setTimeout(
        () => finish(true),
        retryDelaysMs[attempt - 1],
      )
      cancelWait = () => finish(false)
      cancelRecoveryWaitRef.current = cancelWait
    })
    if (!delayElapsed || !mountedRef.current || !recoveryInProgressRef.current) {
      recoveryInProgressRef.current = false
      return
    }
    recoveryInProgressRef.current = false
    setReconnectKey((value) => value + 1)
  }, [disconnectRoom])

  const resolveEmailReview = useCallback(async (action: "send" | "reject") => {
    const review = emailReview
    if (!review || emailReviewBusy !== null || reviewRecipientBusy) return

    setEmailReviewBusy(action)
    setEmailReviewNotice(null)
    setError(null)
    try {
      if (action === "send") {
        const execution = await approveAndExecuteConfirmation(review.confirmationId)
        setEmailReview(null)
        setReviewRecipientDraft("")
        if (execution.success) {
          setEmailReviewNotice("NOVA confirmed the email was accepted by the configured provider.")
        } else {
          setEmailReviewNotice(
            execution.error
              || "NOVA could not confirm that the email was sent. Check Gmail Sent before retrying.",
          )
        }
      } else {
        await rejectConfirmation(review.confirmationId)
        setEmailReview(null)
        setReviewRecipientDraft("")
        setEmailReviewNotice("Email draft rejected. NOVA did not send it.")
      }
    } catch (reviewError) {
      const message = reviewError instanceof ApiRequestError
        ? reviewError.detail
        : reviewError instanceof Error
          ? reviewError.message
          : "NOVA could not resolve this email confirmation."
      setError(
        action === "send"
          ? "The send result could not be verified. Check Gmail Sent before retrying to avoid a duplicate. " + message
          : message,
      )
    } finally {
      setEmailReviewBusy(null)
    }
  }, [emailReview, emailReviewBusy, reviewRecipientBusy])

  const updateReviewRecipient = useCallback(async () => {
    const review = emailReview
    const recipient = reviewRecipientDraft.trim()
    if (!review || reviewRecipientBusy || emailReviewBusy !== null) return
    if (!new RegExp("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}$").test(recipient)) {
      setEmailReviewNotice("Enter one valid email address, then update the recipient.")
      return
    }

    setReviewRecipientBusy(true)
    setEmailReviewNotice(null)
    setError(null)
    try {
      const updated = await updateEmailConfirmationRecipient(
        review.confirmationId,
        recipient,
      )
      if (updated.status !== "pending" || updated.tool !== "email" || updated.action !== "send") {
        throw new Error("This email confirmation is no longer editable. Refresh the draft before sending.")
      }
      const savedRecipient = formatEmailPreviewValue(updated.data?.to, recipient)
      setEmailReview((current) => current && current.confirmationId === review.confirmationId
        ? { ...current, preview: { ...current.preview, to: savedRecipient } }
        : current)
      setReviewRecipientDraft(savedRecipient)
      setEmailReviewNotice(
        "Recipient updated. Check the To field above; the email has not been sent.",
      )
    } catch (reviewError) {
      const message = reviewError instanceof ApiRequestError
        ? reviewError.detail
        : reviewError instanceof Error
          ? reviewError.message
          : "NOVA could not update the email recipient."
      setError(message)
    } finally {
      setReviewRecipientBusy(false)
    }
  }, [emailReview, emailReviewBusy, reviewRecipientBusy, reviewRecipientDraft])

  const submitTypedEmailRecipient = useCallback(async () => {
    const recipient = typedEmailDraft.trim()
    if (!new RegExp("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}$").test(recipient)) {
      setTypedEmailNotice("Enter one valid email address.")
      return
    }
    const room = roomRef.current
    if (!room || !connected) {
      setTypedEmailNotice("Connect NOVA voice first, then submit the address.")
      return
    }

    setTypedEmailBusy(true)
    setTypedEmailNotice(null)
    try {
      await room.localParticipant.publishData(
        new TextEncoder().encode(JSON.stringify({
          type: "nova.email_recipient",
          recipient_email: recipient,
        })),
        { reliable: true, topic: "nova-voice-input" },
      )
      setTypedEmailNotice("Address submitted to NOVA. Waiting for the voice session to acknowledge it…")
    } catch (submitError) {
      setTypedEmailNotice(
        submitError instanceof Error
          ? "Could not submit the address: " + submitError.message
          : "Could not submit the address to NOVA. Please try again.",
      )
    } finally {
      setTypedEmailBusy(false)
    }
  }, [connected, typedEmailDraft])

  const connectRoom = useCallback(async () => {
    if (connectingRef.current || roomRef.current || !mountedRef.current) return
    connectingRef.current = true
    setPhase("connecting")
    setError(null)

    let room: Room | null = null
    let activeLeaseId: string | null = null
    try {
      let activeConversationId = conversationId
      if (activeConversationId) {
        try {
          const history = await apiRequestWithRefresh<{
            conversation_id: number
            messages: Array<{ role: string; content: string }>
          }>(`/conversations/${activeConversationId}/messages?limit=100`)

          const restoredMessages: TranscriptMessage[] = history.messages
            .filter((message) =>
              (message.role === "user" || message.role === "assistant")
              && Boolean(message.content?.trim())
            )
            .slice(-40)
            .map((message, index) => ({
              id: `history-${activeConversationId}-${index}`,
              speaker: message.role as TranscriptSpeaker,
              text: message.content,
              final: true,
              updatedAt: Date.now() + index,
            }))

          if (mountedRef.current) {
            setMessages((current) => current.length ? current : restoredMessages)
          }
        } catch (historyError) {
          if (!(historyError instanceof ApiRequestError) || historyError.status !== 404) {
            throw historyError
          }
          // The last-selected conversation may have been deleted in another view.
          activeConversationId = null
          storeConversationId(null)
          if (mountedRef.current) setConversationId(null)
        }
      }

      if (!activeConversationId) {
        const created = await apiRequestWithRefresh<ConversationCreated>(
          "/conversations",
          {
            method: "POST",
            body: JSON.stringify({ title: "NOVA Voice Conversation" }),
          },
        )
        activeConversationId = created.id
        storeConversationId(created.id)
        if (mountedRef.current) setConversationId(created.id)
      }

      const tokenPath = "/voice/livekit/token?conversation_id="
        + encodeURIComponent(String(activeConversationId))
        + "&language=multi"
      const tokenData = await apiRequestWithRefresh<LiveKitTokenResponse>(
        tokenPath,
        { method: "POST" },
      )
      activeLeaseId = tokenData.room_name || null
      if (!tokenData.server_url || !tokenData.token || !activeLeaseId) {
        void releaseVoiceLease(activeLeaseId)
        activeLeaseId = null
        throw new Error("NOVA received an incomplete secure WebRTC room token.")
      }
      if (!mountedRef.current) {
        void releaseVoiceLease(activeLeaseId)
        activeLeaseId = null
        return
      }
      leaseSessionIdRef.current = activeLeaseId
      setLeaseSessionId(activeLeaseId)

      room = new Room({
        adaptiveStream: false,
        dynacast: false,
        audioCaptureDefaults: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
        },
      })
      roomRef.current = room

      room.on(RoomEvent.Connected, () => {
        if (roomRef.current !== room) return
        setConnected(true)
        // Room signaling alone is not a complete NOVA voice connection.
        setPhase(agentJoinedRef.current ? "listening" : "connecting")
        setError(null)
      })

      room.on(RoomEvent.ParticipantConnected, (participant) => {
        if (roomRef.current !== room || !participant.isAgent) return
        agentJoinedRef.current = true
        if (agentJoinTimeoutRef.current !== null) {
          window.clearTimeout(agentJoinTimeoutRef.current)
          agentJoinTimeoutRef.current = null
        }
        setConnected(true)
        setPhase("listening")
        setError(null)
        void playEntryChime()
      })

      room.on(RoomEvent.ParticipantDisconnected, (participant) => {
        if (roomRef.current !== room || !participant.isAgent) return
        // An API lease heartbeat can remain healthy after the LiveKit agent
        // worker disappears. Reconnect once when the actual agent leaves the
        // room; a second failure in the same minute stops and asks for a manual
        // retry instead of creating a reconnect loop.
        clearResponseWatchdog()
        void recoverAfterAgentDisconnect()
      })

      room.on(RoomEvent.Reconnecting, () => {
        if (roomRef.current === room) setPhase("connecting")
      })

      room.on(RoomEvent.Reconnected, () => {
        if (roomRef.current !== room) return
        setConnected(true)
        setPhase(agentJoinedRef.current ? "listening" : "connecting")
        setError(null)
      })

      room.on(RoomEvent.Disconnected, () => {
        if (roomRef.current !== room) return
        clearResponseWatchdog()
        roomRef.current = null
        agentJoinedRef.current = false
        if (agentJoinTimeoutRef.current !== null) {
          window.clearTimeout(agentJoinTimeoutRef.current)
          agentJoinTimeoutRef.current = null
        }
        setConnected(false)
        setNeedsAudioTap(false)
        const sessionId = leaseSessionIdRef.current
        leaseSessionIdRef.current = null
        setLeaseSessionId(null)
        void releaseVoiceLease(sessionId)
        setPhase("disconnected")
        setError((current) => current ?? "Voice connection ended. Reconnect to continue.")
      })

      room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
        if (track.kind !== Track.Kind.Audio) return
        const element = track.attach()
        element.autoplay = true
        element.setAttribute("data-nova-livekit-audio", "true")
        audioSinkRef.current?.appendChild(element)
        const subscribedRoom = room
        if (subscribedRoom && roomRef.current === subscribedRoom) {
          void subscribedRoom.startAudio().then(() => {
            if (roomRef.current === subscribedRoom) {
              setNeedsAudioTap(!subscribedRoom.canPlaybackAudio)
            }
          }).catch(() => {
            if (roomRef.current === subscribedRoom) setNeedsAudioTap(true)
          })
        }
        if (participant.isAgent && roomRef.current === room) {
          agentJoinedRef.current = true
          if (agentJoinTimeoutRef.current !== null) {
            window.clearTimeout(agentJoinTimeoutRef.current)
            agentJoinTimeoutRef.current = null
          }
          setPhase("speaking")
        }
      })

      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        for (const element of track.detach()) element.remove()
      })

      room.on(RoomEvent.AudioPlaybackStatusChanged, (playing: boolean) => {
        setNeedsAudioTap(!playing)
      })

      room.on(RoomEvent.ActiveSpeakersChanged, (speakers: Participant[]) => {
        if (roomRef.current !== room) return
        const agentSpeaking = speakers.some((speaker) => speaker.isAgent)
        if (agentSpeaking) {
          if (agentSilenceFallbackRef.current !== null) {
            window.clearTimeout(agentSilenceFallbackRef.current)
            agentSilenceFallbackRef.current = null
          }
        } else {
          if (agentSilenceFallbackRef.current !== null) {
            window.clearTimeout(agentSilenceFallbackRef.current)
          }
          agentSilenceFallbackRef.current = window.setTimeout(() => {
            agentSilenceFallbackRef.current = null
            if (roomRef.current !== room || !agentJoinedRef.current) return
            setPhase((current) => current === "speaking" ? "listening" : current)
          }, 1200)
        }
        setPhase((current) => {
          if (!agentJoinedRef.current) return "connecting"
          if (current === "thinking") return current
          if (agentSpeaking) return "speaking"

          // Keep the provider state as the primary source of truth. The
          // debounced silence fallback above only recovers a stuck SPEAKING UI
          // when the provider omits its final listening transition.
          return current
        })
      })

      room.on(RoomEvent.DataReceived, (payload, participant, _kind, topic) => {
        if (topic !== "nova-voice" || !participant?.isAgent) return
        try {
          const event = JSON.parse(new TextDecoder().decode(payload)) as VoiceWireEvent
          if (event.type === "nova.transcript" && event.text?.trim()) {
            const speaker = event.speaker === "assistant" ? "assistant" : "user"
            const id = event.id || createMessageId(speaker)

            if (speaker === "user") {
              // Partial transcripts arrive while the user is still speaking.
              // Only a final transcript means the full turn is ready to process.
              setError(null)
              if (Boolean(event.final)) {
                setPhase("thinking")
                clearResponseWatchdog()
                responseWatchdogRef.current = window.setTimeout(() => {
                  if (roomRef.current !== room) return
                  responseWatchdogRef.current = null
                  // This is deliberately non-fatal. A slow tool/provider must
                  // never tear down a healthy voice room or tell users to retry
                  // an action that might still be executing.
                  setError(
                    "NOVA is taking longer than expected. Your voice session is still connected; please wait, or reconnect only if audio has stopped.",
                  )
                }, 60000)
              }
            } else {
              clearResponseWatchdog()
              setError(null)
              // Receiving actual model output proves the Gemini session is healthy;
              // a later failure should start a new recovery window.
              firstAutomaticRecoveryAtRef.current = 0
              automaticRecoveryAttemptsRef.current = 0
            }

            upsertTranscript(speaker, id, event.text, Boolean(event.final))
          } else if (event.type === "nova.state") {
            const nextPhase = mapAgentState(event.state)
            if (nextPhase === "disconnected") {
              clearResponseWatchdog()
              setPhase("disconnected")
              setError(
                event.reason?.trim()
                  || "NOVA's realtime model connection was lost. Reconnecting the voice session.",
              )
              void recoverAfterAgentDisconnect()
              return
            }
            if (nextPhase === "speaking" || nextPhase === "listening") {
              clearResponseWatchdog()
              setError(null)
            }
            if (nextPhase === "speaking") {
              // The model is delivering a real response, so the session recovered.
              firstAutomaticRecoveryAtRef.current = 0
              automaticRecoveryAttemptsRef.current = 0
            }
            setPhase(nextPhase)
          } else if (event.type === "nova.email_recipient_saved") {
            setTypedEmailBusy(false)
            if (event.ok) {
              const savedRecipient = String(event.recipient_email || "").trim()
              if (savedRecipient) setTypedEmailDraft(savedRecipient)
              setTypedEmailNotice(
                savedRecipient
                  ? `NOVA received ${savedRecipient}. It will use this address for the email draft and still wait for your approval before sending.`
                  : "NOVA received the typed email address.",
              )
              setShowTypedEmailEntry(false)
            } else {
              setTypedEmailNotice(
                String(event.message || "NOVA could not accept that email address."),
              )
            }
          } else if (event.type === "nova.action_preview") {
            const confirmationId = Number(event.confirmation_id)
            if (
              event.tool !== "email"
              || event.action !== "send"
              || !Number.isSafeInteger(confirmationId)
              || confirmationId < 1
            ) {
              return
            }

            const confirmationStatus = String(event.status || "").toLowerCase()
            if (
              confirmationStatus === "pending"
              && event.preview
              && typeof event.preview === "object"
              && !Array.isArray(event.preview)
            ) {
              setEmailReview({
                confirmationId,
                reason: event.reason?.trim() || null,
                preview: event.preview,
              })
              setReviewRecipientDraft(formatEmailPreviewValue(event.preview.to, ""))
              setEmailReviewNotice(null)
            } else if (confirmationStatus && confirmationStatus !== "pending") {
              setEmailReview(null)
              setReviewRecipientDraft("")
              setEmailReviewNotice(
                confirmationStatus === "consumed"
                  ? "NOVA confirmed the email was accepted by the configured provider."
                  : confirmationStatus === "rejected"
                    ? "Email draft rejected. NOVA did not send it."
                    : "Email confirmation resolved with status: " + confirmationStatus + ".",
              )
            }
          }
        } catch {
          // Ignore unknown/malformed room data without breaking the audio session.
        }
      })

      room.on(RoomEvent.TranscriptionReceived, (
        segments: TranscriptionSegment[],
        participant?: Participant,
      ) => {
        if (roomRef.current !== room || !participant?.isAgent) return

        // Render the assistant's actual spoken-audio transcript as a fallback
        // alongside NOVA's authenticated transcript topic. upsertTranscript()
        // reconciles exact/prefix matches so a single utterance stays one card.
        for (const segment of segments) {
          const text = String(segment.text || "").trim()
          if (!text) continue
          upsertTranscript(
            "assistant",
            String(segment.id || createMessageId("assistant")),
            text,
            Boolean(segment.final),
          )
        }
      })

      await room.connect(tokenData.server_url, tokenData.token)
      if (roomRef.current !== room || !mountedRef.current) {
        await room.disconnect()
        return
      }

      await room.localParticipant.setMicrophoneEnabled(true)
      await room.startAudio().catch(() => undefined)
      if (mountedRef.current && roomRef.current === room) {
        setNeedsAudioTap(!room.canPlaybackAudio)
        setConnected(true)
        const agentAlreadyJoined = Array.from(room.remoteParticipants.values())
          .some((participant) => participant.isAgent)
        if (agentAlreadyJoined) {
          agentJoinedRef.current = true
          setPhase("listening")
          setError(null)
          void playEntryChime()
        } else {
          setPhase("connecting")
          agentJoinTimeoutRef.current = window.setTimeout(() => {
            if (roomRef.current !== room || agentJoinedRef.current) return
            agentJoinTimeoutRef.current = null
            roomRef.current = null
            const sessionId = leaseSessionIdRef.current
            leaseSessionIdRef.current = null
            setLeaseSessionId(null)
            void releaseVoiceLease(sessionId)
            setConnected(false)
            setPhase("disconnected")
            setError(
              "The WebRTC room connected, but NOVA's voice agent did not join within 60 seconds. The agent may still be warming up; check the LiveKit agent service and retry.",
            )
            void room?.disconnect().catch(() => undefined)
          }, 60000)
        }
      }
    } catch (connectError) {
      agentJoinedRef.current = false
      if (activeLeaseId) {
        if (leaseSessionIdRef.current === activeLeaseId) {
          leaseSessionIdRef.current = null
          setLeaseSessionId(null)
        }
        void releaseVoiceLease(activeLeaseId)
      }
      if (agentJoinTimeoutRef.current !== null) {
        window.clearTimeout(agentJoinTimeoutRef.current)
        agentJoinTimeoutRef.current = null
      }
      if (roomRef.current === room) roomRef.current = null
      if (room) {
        try {
          await room.disconnect()
        } catch {
          // Ignore cleanup failures after a failed connection attempt.
        }
      }
      if (mountedRef.current) {
        setNeedsAudioTap(false)
        const message = connectError instanceof Error ? connectError.message : ""
        setError(message || "NOVA could not connect to its local LiveKit WebRTC service.")
        setConnected(false)
        setPhase("disconnected")
      }
    } finally {
      connectingRef.current = false
    }
  }, [clearResponseWatchdog, conversationId, disconnectRoom, playEntryChime, recoverAfterAgentDisconnect, releaseVoiceLease, upsertTranscript])

  useEffect(() => {
    if (!connected || !leaseSessionId) return

    let stopped = false
    const heartbeatUrl = "/voice/livekit/lease/heartbeat?session_id="
      + encodeURIComponent(leaseSessionId)

    const timer = window.setInterval(() => {
      if (stopped || leaseSessionIdRef.current !== leaseSessionId) return
      void apiRequestWithRefresh<{ renewed: boolean }>(
        heartbeatUrl,
        { method: "POST" },
      ).then((result) => {
        if (result.renewed || stopped || leaseSessionIdRef.current !== leaseSessionId) return
        void disconnectRoom().then(() => {
          if (!mountedRef.current) return
          setPhase("disconnected")
          setError("This voice session is no longer the active session. Reconnect before sending another request.")
        })
      }).catch(() => {
        // Retry on the next heartbeat after transient network/backend errors.
      })
    }, 30000)

    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [connected, disconnectRoom, leaseSessionId])

  const toggleVoice = useCallback(() => {
    const activeRoom = roomRef.current
    if (activeRoom) {
      // Browsers can allow the WebRTC room but block audio autoplay. Use
      // this first orb tap as the required user gesture instead of hanging up.
      if (needsAudioTap || !activeRoom.canPlaybackAudio) {
        void activeRoom.startAudio().then(() => {
          if (roomRef.current !== activeRoom) return
          const playbackReady = activeRoom.canPlaybackAudio
          setNeedsAudioTap(!playbackReady)
          setError(
            playbackReady
              ? null
              : "Browser audio is still blocked. Allow sound for NOVA in the browser site settings, then tap the orb again.",
          )
        }).catch(() => {
          if (roomRef.current === activeRoom) {
            setNeedsAudioTap(true)
            setError("Browser audio is blocked. Allow sound for NOVA in the browser site settings, then tap the orb again.")
          }
        })
        return
      }

      void disconnectRoom().then(() => {
        if (mountedRef.current) {
          setPhase("disconnected")
          setError(null)
        }
      })
      return
    }
    // A deliberate manual retry starts a fresh recovery budget.
    firstAutomaticRecoveryAtRef.current = 0
    automaticRecoveryAttemptsRef.current = 0
    void connectRoom()
  }, [connectRoom, disconnectRoom, needsAudioTap])

  const startNewVoiceConversation = useCallback(async () => {
    // Avoid overlapping conversation creation or changing context while the
    // first room connection is still being established.
    if (creatingConversation || (phase === "connecting" && !connected)) return

    setCreatingConversation(true)
    setError(null)

    try {
      // Create the new thread first so an API failure doesn't interrupt the
      // currently working voice conversation.
      const created = await apiRequestWithRefresh<ConversationCreated>(
        "/conversations",
        {
          method: "POST",
          body: JSON.stringify({ title: "NOVA Voice Conversation" }),
        },
      )

      await disconnectRoom()
      storeConversationId(created.id)
      setConversationId(created.id)
      setMessages([])
      setEmailReview(null)
      setEmailReviewNotice(null)
      setReviewRecipientDraft("")
      setShowTypedEmailEntry(false)
      setTypedEmailDraft("")
      setTypedEmailNotice(null)
      setNeedsAudioTap(false)
      setPhase("connecting")
      setReconnectKey((value) => value + 1)
    } catch (newConversationError) {
      const message = newConversationError instanceof Error
        ? newConversationError.message
        : ""
      setError(
        message
          || "NOVA could not start a new voice conversation. Your current conversation remains selected.",
      )
    } finally {
      setCreatingConversation(false)
    }
  }, [connected, creatingConversation, disconnectRoom, phase])

  useEffect(() => {
    mountedRef.current = true
    void connectRoom()
    return () => {
      mountedRef.current = false
      if (recoveryTimerRef.current !== null) {
        window.clearTimeout(recoveryTimerRef.current)
        recoveryTimerRef.current = null
      }
      const cancelRecoveryWait = cancelRecoveryWaitRef.current
      cancelRecoveryWaitRef.current = null
      if (cancelRecoveryWait) cancelRecoveryWait()
      recoveryInProgressRef.current = false
      const activeRoom = roomRef.current
      roomRef.current = null
      const sessionId = leaseSessionIdRef.current
      leaseSessionIdRef.current = null
      void releaseVoiceLease(sessionId)
      clearResponseWatchdog()
      setNeedsAudioTap(false)
      agentJoinedRef.current = false
      if (agentJoinTimeoutRef.current !== null) {
        window.clearTimeout(agentJoinTimeoutRef.current)
        agentJoinTimeoutRef.current = null
      }
      if (activeRoom) void activeRoom.disconnect().catch(() => undefined)
    }
  }, [reconnectKey, releaseVoiceLease]) // Explicit retry remounts the session only when requested.

  useEffect(() => {
    const panel = transcriptPanelRef.current
    if (panel) panel.scrollTop = panel.scrollHeight
  }, [messages])

  const statusLabel = connected && needsAudioTap
    ? "TAP ORB FOR AUDIO"
    : phase === "listening" && !connected
      ? "VOICE STANDBY"
      : phase === "listening"
        ? "LISTENING"
        : phase === "thinking"
          ? "THINKING"
          : phase === "speaking"
            ? "SPEAKING"
            : phase === "connecting"
              ? "CONNECTING"
              : "DISCONNECTED"

  const buttonLabel = connected && needsAudioTap
    ? "Enable voice audio"
    : connected
      ? "End voice conversation"
      : phase === "connecting"
        ? "Connecting to NOVA"
        : "Reconnect voice"

  return (
    <div className="voice-shell livekit-voice-shell">
      <header className="voice-header">
        <button
          className="voice-icon-action voice-exit-action"
          type="button"
          onClick={() => {
            void disconnectRoom()
            onOpenConversation()
          }}
          aria-label="Back to conversation"
          title="Back to conversation"
        >
          <Icon name="close" size={18} />
        </button>
        <div className="voice-brand-state" aria-live="polite">
          <div className="voice-brand-label">NOVA · VOICE</div>
          <div className={"voice-live-state " + phase}>{statusLabel}</div>
        </div>
        <button
          className="voice-icon-action voice-new-conversation-action"
          type="button"
          onClick={() => void startNewVoiceConversation()}
          disabled={creatingConversation || (phase === "connecting" && !connected)}
          aria-label={creatingConversation ? "Starting new voice conversation" : "New voice conversation"}
          aria-busy={creatingConversation}
          title={creatingConversation ? "Starting new conversation…" : "New voice conversation"}
        >
          <Icon name="plus" size={18} />
          <span>{creatingConversation ? "Starting…" : "New chat"}</span>
        </button>
      </header>

      <main className="voice-main">
        <section className="voice-stage livekit-voice-stage" aria-label="NOVA realtime voice">
          <button
            className={"voice-orb voice-orb-" + phase}
            type="button"
            onClick={toggleVoice}
            disabled={phase === "connecting" && !connected}
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
            className="voice-live-transcript"
            aria-label="Live voice conversation"
            aria-live="polite"
            aria-relevant="additions text"
          >
            {messages.length === 0 && (
              <p className="voice-transcript-placeholder">
                {connected
                  ? "Go ahead — I'm listening."
                  : phase === "connecting"
                    ? "Connecting your voice…"
                    : "Tap the orb to reconnect."}
              </p>
            )}
            {messages.filter((message, index, items) => message.speaker !== "assistant" || index === 0 || items[index - 1].speaker !== "assistant" || normalizeTranscriptForDedupe(items[index - 1].text) !== normalizeTranscriptForDedupe(message.text)).map((message) => (
              <div
                className={"voice-turn-card " + (message.speaker === "user" ? "user" : "assistant")}
                key={message.id}
              >
                <div className="voice-turn-label">
                  {message.speaker === "user" ? "YOU" : "NOVA"}
                </div>
                <p>{renderTranscriptText(message.text)}</p>
              </div>
            ))}
            <section className="voice-typed-email-entry" aria-label="Type an email recipient">
              <button
                type="button"
                className="voice-typed-email-toggle"
                onClick={() => {
                  setShowTypedEmailEntry((shown) => !shown)
                  setTypedEmailNotice(null)
                }}
                aria-expanded={showTypedEmailEntry}
              >
                <Icon name="message" size={14} />
                <span>{showTypedEmailEntry ? "Hide email entry" : "Type email instead"}</span>
              </button>
              {showTypedEmailEntry && (
                <form
                  className="voice-typed-email-form"
                  onSubmit={(event) => {
                    event.preventDefault()
                    void submitTypedEmailRecipient()
                  }}
                >
                  <label htmlFor="nova-typed-email-recipient">Recipient email</label>
                  <input
                    id="nova-typed-email-recipient"
                    className="voice-typed-email-input"
                    type="email"
                    inputMode="email"
                    autoComplete="email"
                    required
                    placeholder="name@example.com"
                    value={typedEmailDraft}
                    onChange={(event) => setTypedEmailDraft(event.target.value)}
                    disabled={typedEmailBusy}
                  />
                  <p>Type or paste the exact address here if NOVA might mishear it. NOVA will continue the email flow and show a preview; it will not send without your approval.</p>
                  <button
                    type="submit"
                    className="voice-typed-email-submit"
                    disabled={!connected || typedEmailBusy}
                  >
                    {typedEmailBusy ? "Submitting…" : "Use this email"}
                  </button>
                </form>
              )}
              {typedEmailNotice && (
                <p className="voice-typed-email-notice" role="status">{typedEmailNotice}</p>
              )}
            </section>
            {emailReview && (
              <section className="voice-email-review" aria-label="Email draft review">
                <div className="voice-email-review-heading">
                  <div className="voice-turn-label">EMAIL DRAFT · REVIEW BEFORE SENDING</div>
                  <span>AWAITING APPROVAL</span>
                </div>
                {emailReview.reason && <p className="voice-email-review-reason">{emailReview.reason}</p>}
                <dl className="voice-email-review-fields">
                  <div>
                    <dt>To</dt>
                    <dd>{formatEmailPreviewValue(emailReview.preview.to, "Not specified")}</dd>
                  </div>
                  {emailReview.preview.cc !== null && emailReview.preview.cc !== undefined && emailReview.preview.cc !== "" && (
                    <div>
                      <dt>CC</dt>
                      <dd>{formatEmailPreviewValue(emailReview.preview.cc, "—")}</dd>
                    </div>
                  )}
                  {emailReview.preview.bcc !== null && emailReview.preview.bcc !== undefined && emailReview.preview.bcc !== "" && (
                    <div>
                      <dt>BCC</dt>
                      <dd>{formatEmailPreviewValue(emailReview.preview.bcc, "—")}</dd>
                    </div>
                  )}
                  <div>
                    <dt>Subject</dt>
                    <dd>{formatEmailPreviewValue(emailReview.preview.subject, "(No subject)")}</dd>
                  </div>
                </dl>
                <div className="voice-email-recipient-editor">
                  <label htmlFor="nova-review-recipient">Correct recipient (type or paste)</label>
                  <div className="voice-email-recipient-editor-row">
                    <input
                      id="nova-review-recipient"
                      className="voice-email-recipient-input"
                      type="email"
                      inputMode="email"
                      autoComplete="email"
                      required
                      value={reviewRecipientDraft}
                      onChange={(event) => setReviewRecipientDraft(event.target.value)}
                      disabled={reviewRecipientBusy || emailReviewBusy !== null}
                    />
                    <button
                      type="button"
                      className="voice-email-recipient-update"
                      onClick={() => void updateReviewRecipient()}
                      disabled={reviewRecipientBusy || emailReviewBusy !== null}
                    >
                      {reviewRecipientBusy ? "Saving…" : "Update recipient"}
                    </button>
                  </div>
                  <p>Update the saved recipient before sending. The To field above changes only after this update succeeds.</p>
                </div>
                <div className="voice-email-review-label">MESSAGE</div>
                <div className="voice-email-review-body">
                  {formatEmailPreviewValue(emailReview.preview.body, "(Empty draft)")}
                </div>
                <div className="voice-email-review-actions">
                  <button
                    type="button"
                    className="voice-email-review-reject"
                    onClick={() => void resolveEmailReview("reject")}
                    disabled={emailReviewBusy !== null || reviewRecipientBusy}
                  >
                    {emailReviewBusy === "reject" ? "Rejecting…" : "Reject"}
                  </button>
                  <button
                    type="button"
                    className="voice-email-review-send"
                    onClick={() => void resolveEmailReview("send")}
                    disabled={emailReviewBusy !== null || reviewRecipientBusy}
                  >
                    {emailReviewBusy === "send" ? "Sending…" : "Send email"}
                  </button>
                </div>
              </section>
            )}
            {emailReviewNotice && (
              <p className="voice-email-review-notice" role="status">
                {emailReviewNotice}
              </p>
            )}
          </div>

          {error && (
            <div className="voice-error livekit-voice-error" role="alert">
              <span>{error}</span>
              <button
                type="button"
                onClick={() => {
                  setError(null)
                  setReconnectKey((value) => value + 1)
                }}
              >
                Reconnect
              </button>
            </div>
          )}

          <div className="livekit-audio-sink" ref={audioSinkRef} aria-hidden="true" />
        </section>

        <footer className="voice-footer livekit-voice-footer">
          <span>{connected ? "Real-time WebRTC audio" : "NOVA Voice"}</span>
          <span className="voice-footer-divider" aria-hidden="true">·</span>
          <span>{connected ? "Speak naturally — interrupt at any time" : "Private voice session"}</span>
        </footer>
      </main>
    </div>
  )
}
