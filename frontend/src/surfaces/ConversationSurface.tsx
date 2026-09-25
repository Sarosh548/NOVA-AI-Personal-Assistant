import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"

import { ApiRequestError } from "../api/client"
import {
  deleteConversation,
  getConversationMessages,
  getConversations,
  sendChatMessage,
  updateConversationTitle,
} from "../api/conversations"
import type { Conversation, ConversationMessage } from "../api/types"
import { Icon } from "../components/Icon"

type RetryPayload = {
  message: string
  conversationId: number | null
  idempotencyKey: string
}

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
  const [draft, setDraft] = useState("")
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
  const endRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const loadMessages = useCallback(async (id: number) => {
    setLoadingMessages(true)
    setError(null)
    setErrorAction(null)
    try {
      const result = await getConversationMessages(id)
      setMessages(result.messages)
    } catch (err) {
      setMessages([])
      setError(formatApiError(err, "NOVA could not load this conversation."))
    } finally {
      setLoadingMessages(false)
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

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, sending])

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

  const newConversation = () => {
    if (sending || savingId !== null || deletingId !== null) return
    setActiveId(null)
    setMessages([])
    setDraft("")
    setEditingId(null)
    setRetryPayload(null)
    clearError()
    textareaRef.current?.focus()
  }

  const selectConversation = async (id: number) => {
    if (sending || savingId !== null || deletingId !== null || id === activeId) return
    setActiveId(id)
    setEditingId(null)
    setRetryPayload(null)
    clearError()
    await loadMessages(id)
  }

  const sendMessage = async (payload: RetryPayload, optimistic: boolean) => {
    setError(null)
    setErrorAction(null)
    setSending(true)

    if (optimistic) {
      setMessages((current) => [...current, { role: "user", content: payload.message }])
    }

    try {
      const result = await sendChatMessage(payload)
      setActiveId(result.conversation_id)
      setMessages((current) => [...current, { role: "assistant", content: result.response }])
      await refreshConversations()
      setRetryPayload(null)
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
    const message = draft.trim()
    if (!message || sending) return

    setDraft("")
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
            {sending ? "Thinking" : "Ready"}
          </div>
        </header>

        <div className="message-scroll-area">
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
              <div ref={endRef} />
            </div>
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
          <textarea
            ref={textareaRef}
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
          <button
            className="composer-send"
            type="submit"
            aria-label="Send message"
            disabled={!draft.trim() || sending}
          >
            <Icon name="arrow" size={18} />
          </button>
        </form>
        <div className="composer-hint">Enter to send · Shift + Enter for a new line</div>
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
