import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"

import { ApiRequestError } from "../api/client"
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
  const [conversationState, setConversationState] = useState<ConversationState | null>(null)
  const [assistantMeta, setAssistantMeta] = useState<ChatResponse | null>(null)
  const [confirmationBusy, setConfirmationBusy] = useState<"approve" | "reject" | null>(null)
  const [confirmationNotice, setConfirmationNotice] = useState<string | null>(null)
  const [creatingConversation, setCreatingConversation] = useState(false)
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
    setAssistantMeta(null)
    setConfirmationNotice(null)

    try {
      const result = await getConversationMessages(id)
      setMessages(result.messages)

      try {
        setConversationState(await getConversationState(id))
      } catch {
        setConversationState(null)
      }
    } catch (err) {
      setMessages([])
      setConversationState(null)
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

  const newConversation = async () => {
    if (
      sending ||
      savingId !== null ||
      deletingId !== null ||
      creatingConversation
    ) return

    setCreatingConversation(true)
    setEditingId(null)
    setRetryPayload(null)
    clearError()
    setAssistantMeta(null)
    setConfirmationNotice(null)

    try {
      const result = await createConversation()
      setActiveId(result.id)
      setMessages([])
      setDraft("")
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
      await refreshConversations()

      try {
        setConversationState(await getConversationState(result.conversation_id))
      } catch {
        setConversationState(null)
      }

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
            {conversationState ? formatConversationState(conversationState) : sending ? "Thinking" : "Ready"}
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
              {assistantMeta && (
                <ConversationResponseDetails
                  response={assistantMeta}
                  confirmationNotice={confirmationNotice}
                  confirmationBusy={confirmationBusy}
                  onConfirmation={handleConfirmation}
                />
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

function formatConversationState(snapshot: ConversationState): string {
  const state = snapshot.state.trim().toLowerCase()
  if (snapshot.should_listen || state === "listening") return "Listening"
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
  const confirmation = isRecord(response.confirmation) ? response.confirmation : null
  const confirmationId = confirmation ? Number(confirmation.id) : NaN
  const confirmationStatus = confirmation
    ? String(confirmation.status ?? "pending").toLowerCase()
    : null
  const sources: Array<Record<string, unknown>> = [
    ...(response.web_sources ?? []).map((source) => ({ ...source, kind: "Web" })),
    ...(response.knowledge_sources ?? []).map((source) => ({ ...source, kind: "Knowledge" })),
  ]
  const resultBlocks = [
    response.tool_result ? { label: "Action", value: response.tool_result } : null,
    response.workflow_result ? { label: "Workflow", value: response.workflow_result } : null,
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
          {canActOnConfirmation && (
            <div className="conversation-detail-actions">
              <button className="secondary-action" type="button" onClick={() => onConfirmation(confirmationId, "reject")} disabled={confirmationBusy !== null}>
                {confirmationBusy === "reject" ? "Rejecting…" : "Reject"}
              </button>
              <button className="primary-action" type="button" onClick={() => onConfirmation(confirmationId, "approve")} disabled={confirmationBusy !== null}>
                {confirmationBusy === "approve" ? "Approving…" : "Approve & execute"}
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
