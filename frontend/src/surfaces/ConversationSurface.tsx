import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"

import { ApiRequestError } from "../api/client"
import {
  getConversationMessages,
  getConversations,
  sendChatMessage,
} from "../api/conversations"
import type { Conversation, ConversationMessage } from "../api/types"
import { Icon } from "../components/Icon"

function requestId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `nova-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()

  return new Intl.DateTimeFormat(undefined, sameDay
    ? { hour: "numeric", minute: "2-digit" }
    : { month: "short", day: "numeric" }).format(date)
}

export function ConversationSurface() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [draft, setDraft] = useState("")
  const [loading, setLoading] = useState(true)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const loadMessages = useCallback(async (id: number) => {
    setLoadingMessages(true)
    setError(null)
    try {
      const result = await getConversationMessages(id)
      setMessages(result.messages)
    } catch (err) {
      setMessages([])
      setError(err instanceof ApiRequestError ? err.detail : "NOVA could not load this conversation.")
    } finally {
      setLoadingMessages(false)
    }
  }, [])

  const loadConversations = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await getConversations()
      setConversations(result)
      if (result.length === 0) {
        setActiveId(null)
        setMessages([])
        return
      }
      const selected = result.find((item) => item.id === activeId) ?? result[0]
      setActiveId(selected.id)
      await loadMessages(selected.id)
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.detail : "NOVA could not load your conversations.")
    } finally {
      setLoading(false)
    }
  }, [activeId, loadMessages])

  useEffect(() => { void loadConversations() }, [loadConversations])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }) }, [messages, sending])

  const newConversation = () => {
    if (sending) return
    setActiveId(null)
    setMessages([])
    setDraft("")
    setError(null)
  }

  const selectConversation = async (id: number) => {
    if (sending || id === activeId) return
    setActiveId(id)
    await loadMessages(id)
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const message = draft.trim()
    if (!message || sending) return

    setDraft("")
    setError(null)
    setSending(true)
    setMessages((current) => [...current, { role: "user", content: message }])

    try {
      const result = await sendChatMessage({
        message,
        conversationId: activeId,
        idempotencyKey: requestId(),
      })
      setActiveId(result.conversation_id)
      setMessages((current) => [...current, { role: "assistant", content: result.response }])
      setConversations(await getConversations())
    } catch (err) {
      setError(err instanceof ApiRequestError ? err.detail : "NOVA could not complete that message.")
    } finally {
      setSending(false)
    }
  }

  const active = conversations.find((item) => item.id === activeId)

  return (
    <div className="conversation-shell">
      <aside className="conversation-sidebar">
        <div className="conversation-sidebar-header">
          <div>
            <div className="section-kicker">CONVERSATIONS</div>
            <h1>Your threads</h1>
          </div>
          <button className="icon-action" type="button" aria-label="New conversation" onClick={newConversation} disabled={sending}>
            <Icon name="plus" size={18} />
          </button>
        </div>

        <button className="conversation-new-button" type="button" onClick={newConversation} disabled={sending}>
          <Icon name="plus" size={16} />
          New conversation
        </button>

        <div className="conversation-list" aria-label="Conversations">
          {loading ? (
            <div className="conversation-list-state"><div /><div /><div /></div>
          ) : conversations.length === 0 ? (
            <div className="conversation-list-empty">No saved conversations yet.<br />Your first message will start one.</div>
          ) : (
            conversations.map((conversation) => (
              <button
                className={conversation.id === activeId ? "conversation-list-item active" : "conversation-list-item"}
                key={conversation.id}
                type="button"
                onClick={() => void selectConversation(conversation.id)}
                disabled={sending}
              >
                <span>{conversation.title || "New Conversation"}</span>
                <small>{formatTime(conversation.updated_at)}</small>
              </button>
            ))
          )}
        </div>
      </aside>

      <section className="conversation-panel">
        <header className="conversation-header">
          <div>
            <div className="section-kicker">NOVA</div>
            <h2>{active?.title || "New conversation"}</h2>
          </div>
          <div className="conversation-state"><span className="connection-dot" /> Ready</div>
        </header>

        <div className="message-scroll-area">
          {loadingMessages ? (
            <div className="conversation-empty"><div className="loading-pulse" /><span>Opening conversation…</span></div>
          ) : messages.length === 0 ? (
            <div className="conversation-empty">
              <div className="conversation-empty-orb"><Icon name="spark" size={24} /></div>
              <div className="section-kicker">START WITH NOVA</div>
              <h3>What should we work on?</h3>
              <p>Ask a question, plan something, research a topic, or tell NOVA what you need handled.</p>
            </div>
          ) : (
            <div className="message-stack">
              {messages.map((message, index) => (
                <MessageBubble key={`${message.role}-${index}`} message={message} />
              ))}
              {sending && (
                <div className="message-row assistant">
                  <div className="assistant-avatar"><Icon name="spark" size={14} /></div>
                  <div className="message-bubble assistant"><span>NOVA is thinking…</span><span className="thinking-dots"><i /><i /><i /></span></div>
                </div>
              )}
              <div ref={endRef} />
            </div>
          )}
        </div>

        {error && <div className="conversation-error" role="alert">{error}</div>}

        <form className="conversation-composer" onSubmit={submit}>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
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
          <button className="composer-send" type="submit" aria-label="Send message" disabled={!draft.trim() || sending}>
            <Icon name="arrow" size={18} />
          </button>
        </form>
        <div className="composer-hint">Enter to send · Shift + Enter for a new line</div>
      </section>
    </div>
  )
}

function MessageBubble({ message }: { message: ConversationMessage }) {
  if (message.role === "system") return <div className="message-system">{message.content}</div>
  if (message.role === "user") return <div className="message-row user"><div className="message-bubble user">{message.content}</div></div>
  return <div className="message-row assistant"><div className="assistant-avatar"><Icon name="spark" size={14} /></div><div className="message-bubble assistant">{message.content}</div></div>
}
