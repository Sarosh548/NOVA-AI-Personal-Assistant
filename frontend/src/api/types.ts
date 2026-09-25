export type NovaUser = {
  id: string
  display_name: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type TokenResponse = {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  session_id: string
  user: NovaUser
}

export type ApiError = {
  detail: string | Array<Record<string, unknown>>
}

export type Conversation = {
  id: number
  title: string
  created_at: string
  updated_at: string
}

export type ConversationMessage = {
  role: "user" | "assistant" | "system"
  content: string
}

export type ConversationMessagesResponse = {
  conversation_id: number
  messages: ConversationMessage[]
}

export type ChatResponse = {
  response: string
  conversation_id: number
  understanding?: Record<string, unknown> | null
  plan?: Record<string, unknown> | null
  permission?: Record<string, unknown> | null
  confirmation?: Record<string, unknown> | null
  tool_result?: Record<string, unknown> | null
  workflow_result?: Record<string, unknown> | null
  memory_action?: Record<string, unknown> | null
  knowledge_sources?: Array<Record<string, unknown>>
  web_sources?: Array<Record<string, unknown>>
}
