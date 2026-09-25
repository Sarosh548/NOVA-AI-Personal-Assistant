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
