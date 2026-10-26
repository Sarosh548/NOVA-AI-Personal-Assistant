import { ApiRequestError, apiRequestWithRefresh } from "./client"
import type { ChatResponse, Conversation, ConversationMessagesResponse } from "./types"

export type ConversationState = {
  conversation_id: number
  state: string
  last_role: string | null
  should_listen: boolean
}

export function createConversation(title?: string): Promise<{ id: number }> {
  return apiRequestWithRefresh<{ id: number }>("/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(title ? { title } : {}),
  })
}

export function getConversations(limit = 50): Promise<Conversation[]> {
  return apiRequestWithRefresh<Conversation[]>(`/conversations?limit=${limit}`)
}

export function getConversationMessages(conversationId: number, limit = 100): Promise<ConversationMessagesResponse> {
  return apiRequestWithRefresh<ConversationMessagesResponse>(`/conversations/${conversationId}/messages?limit=${limit}`)
}

const CHAT_RETRYABLE_STATUSES = new Set([0, 408, 425, 429, 502, 503, 504])
const CHAT_RETRY_BACKOFF_MS = [500, 1500] as const

function isRetryableChatRequestError(error: unknown): error is ApiRequestError {
  if (!(error instanceof ApiRequestError)) return false
  if (CHAT_RETRYABLE_STATUSES.has(error.status)) return true
  return error.status === 409 && /already being processed|already in progress/i.test(error.detail)
}

function waitForChatRetry(delayMs: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, delayMs))
}

const CHAT_REQUEST_TIMEOUT_MS = 30_000

async function sendChatRequest(options: RequestInit): Promise<ChatResponse> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    CHAT_REQUEST_TIMEOUT_MS,
  )
  try {
    return await apiRequestWithRefresh<ChatResponse>("/chat", {
      ...options,
      signal: controller.signal,
    })
  } finally {
    window.clearTimeout(timeoutId)
  }
}

export async function sendChatMessage(params: { message: string; conversationId: number | null; idempotencyKey: string }): Promise<ChatResponse> {
  const options: RequestInit = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      // Keep the same key across retries so state-changing requests cannot be duplicated.
      "Idempotency-Key": params.idempotencyKey,
    },
    body: JSON.stringify({
      message: params.message,
      conversation_id: params.conversationId,
    }),
  }

  for (let attempt = 0; ; attempt += 1) {
    try {
      return await sendChatRequest(options)
    } catch (error) {
      const retryDelay = CHAT_RETRY_BACKOFF_MS[attempt]
      if (retryDelay === undefined || !isRetryableChatRequestError(error)) {
        throw error
      }
      await waitForChatRetry(retryDelay)
    }
  }
}

export function getConversationState(conversationId: number): Promise<ConversationState> {
  return apiRequestWithRefresh<ConversationState>(`/conversations/${conversationId}/state`)
}

export function updateConversationTitle(conversationId: number, title: string): Promise<{ updated: boolean }> {
  return apiRequestWithRefresh<{ updated: boolean }>(`/conversations/${conversationId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title }),
  })
}

export function deleteConversation(conversationId: number): Promise<void> {
  return apiRequestWithRefresh<void>(`/conversations/${conversationId}`, {
    method: "DELETE",
  })
}
