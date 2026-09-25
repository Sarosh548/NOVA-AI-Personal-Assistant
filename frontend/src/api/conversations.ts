import { apiRequestWithRefresh } from "./client"
import type { ChatResponse, Conversation, ConversationMessagesResponse } from "./types"

export function getConversations(limit = 50): Promise<Conversation[]> {
  return apiRequestWithRefresh<Conversation[]>(`/conversations?limit=${limit}`)
}

export function getConversationMessages(conversationId: number, limit = 100): Promise<ConversationMessagesResponse> {
  return apiRequestWithRefresh<ConversationMessagesResponse>(`/conversations/${conversationId}/messages?limit=${limit}`)
}

export function sendChatMessage(params: { message: string; conversationId: number | null; idempotencyKey: string }): Promise<ChatResponse> {
  return apiRequestWithRefresh<ChatResponse>("/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": params.idempotencyKey,
    },
    body: JSON.stringify({
      message: params.message,
      conversation_id: params.conversationId,
    }),
  })
}
