import { apiRequestWithRefresh } from "./client"

export type Task = {
  id: number
  title: string
  description: string | null
  status: string
  priority: string
  due_at: string | null
  created_at: string
  updated_at: string
}

export type Reminder = {
  id: number
  title: string
  reminder_time: string
  status: string
}

export type CalendarConnection = {
  id: string
  user_id: string
  provider: string
  calendar_id: string
  scopes: string
  token_expires_at: string | null
  created_at: string
  updated_at: string
}

export type CalendarStatus = {
  connected: boolean
  connection: CalendarConnection | null
}

export type CalendarEvent = {
  id?: string
  summary?: string
  description?: string
  location?: string
  status?: string
  htmlLink?: string
  etag?: string
  start?: { date?: string; dateTime?: string; timeZone?: string }
  end?: { date?: string; dateTime?: string; timeZone?: string }
  attendees?: Array<{
    email?: string
    displayName?: string
    responseStatus?: string
    optional?: boolean
    resource?: boolean
  }>
  [key: string]: unknown
}

export type ActivityEvent = {
  id: number
  conversation_id: number | null
  workflow_id: number | null
  event_type: string
  source: string
  status: string
  title: string
  summary: string
  metadata: Record<string, unknown>
  created_at: string
}

export type Memory = {
  id: number
  memory: string
  category: "identity" | "goal" | "preference" | "project" | "interest" | "context" | "personal"
  importance: "high" | "medium" | "low"
  created_at: string
  updated_at: string
}

export type MemorySearchResult = Memory & {
  similarity: number
  ranking_score: number
}

export type KnowledgeDocument = {
  id: number
  title: string
  source: string | null
  chunk_count: number
  created_at: string
  updated_at: string
}

export type KnowledgeDocumentDetail = KnowledgeDocument & {
  content: string
}

export type KnowledgeSearchResult = {
  document_id: number
  title: string
  source: string | null
  chunk_index: number
  content: string
  similarity: number
}

export type Confirmation = {
  id: number
  conversation_id: number | null
  tool: string
  action: string
  data: Record<string, unknown>
  reason: string
  status: string
  created_at: string
  expires_at: string
  resolved_at: string | null
}

export type ConfirmationExecution = {
  confirmation: Confirmation
  success: boolean
  status: string
  tool_result: Record<string, unknown>
  workflow_result: Record<string, unknown>
  error: string | null
}

export type Permission = {
  id: number
  tool: string
  action:
    | "list"
    | "get"
    | "search"
    | "send"
    | "create"
    | "update"
    | "start"
    | "complete"
    | "cancel"
    | "delete"
  mode: "allow" | "confirm" | "deny"
  created_at: string
  updated_at: string
}

export type WorkflowStep = {
  id: number
  workflow_id: number
  step_id: string
  position: number
  tool: string
  action: string
  data: Record<string, unknown>
  depends_on: string[]
  status: string
  result: Record<string, unknown> | null
  error: string | null
  attempts: number
  created_at: string
  updated_at: string
  started_at: string | null
  completed_at: string | null
}

export type Workflow = {
  id: number
  conversation_id: number | null
  status: string
  execution_mode: string
  scheduled_at: string | null
  plan: Record<string, unknown>
  result: Record<string, unknown> | null
  error: string | null
  created_at: string
  updated_at: string
  started_at: string | null
  completed_at: string | null
  steps: WorkflowStep[]
}

export type NotificationPreferences = {
  id: number
  user_id: string
  timezone: string
  daily_activity_digest_enabled: boolean
  delivery_hour: number
  delivery_minute: number
  created_at: string
  updated_at: string
}

export type NotificationDestination = {
  id: number
  user_id: string
  channel: string
  destination: string
  label: string | null
  is_enabled: boolean
  is_default: boolean
  created_at: string
  updated_at: string
}

const jsonHeaders = {
  "Content-Type": "application/json",
}

export function getTasks(status?: string): Promise<Task[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ""
  return apiRequestWithRefresh<Task[]>(`/tasks${query}`)
}

export function createTask(payload: {
  title: string
  description?: string | null
  priority: string
  due_at?: string | null
}): Promise<{ id: number }> {
  return apiRequestWithRefresh<{ id: number }>("/tasks", {
    method: "POST",
    headers: {
      ...jsonHeaders,
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify(payload),
  })
}

export function updateTask(
  taskId: number,
  payload: { priority?: string; due_at?: string | null },
): Promise<{ updated: boolean }> {
  return apiRequestWithRefresh<{ updated: boolean }>(`/tasks/${taskId}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export function actOnTask(
  taskId: number,
  action: "start" | "complete" | "cancel",
): Promise<{ action: string; updated: boolean }> {
  return apiRequestWithRefresh<{ action: string; updated: boolean }>(
    `/tasks/${taskId}/${action}`,
    { method: "POST" },
  )
}

export function deleteTask(taskId: number): Promise<void> {
  return apiRequestWithRefresh<void>(`/tasks/${taskId}`, {
    method: "DELETE",
  })
}

export function getReminders(): Promise<Reminder[]> {
  return apiRequestWithRefresh<Reminder[]>("/reminders")
}

export function createReminder(payload: {
  title: string
  reminder_time: string
}): Promise<{ id: number }> {
  return apiRequestWithRefresh<{ id: number }>("/reminders", {
    method: "POST",
    headers: {
      ...jsonHeaders,
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify(payload),
  })
}

export function updateReminder(
  reminderId: number,
  payload: { title?: string; reminder_time?: string },
): Promise<{ updated: boolean }> {
  return apiRequestWithRefresh<{ updated: boolean }>(`/reminders/${reminderId}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export function actOnReminder(
  reminderId: number,
  action: "complete" | "cancel",
): Promise<{ action: string; updated: boolean }> {
  return apiRequestWithRefresh<{ action: string; updated: boolean }>(
    `/reminders/${reminderId}/${action}`,
    { method: "POST" },
  )
}

export function deleteReminder(reminderId: number): Promise<void> {
  return apiRequestWithRefresh<void>(`/reminders/${reminderId}`, {
    method: "DELETE",
  })
}

export function getCalendarStatus(): Promise<CalendarStatus> {
  return apiRequestWithRefresh<CalendarStatus>("/integrations/google/calendar/status")
}

export function getCalendarConnectUrl(): Promise<{ authorization_url: string }> {
  return apiRequestWithRefresh<{ authorization_url: string }>(
    "/integrations/google/calendar/connect",
  )
}

export type CalendarSendUpdates = "all" | "externalOnly" | "none"

export type CalendarEventBoundary = {
  date?: string
  dateTime?: string
  timeZone?: string
}

export type CalendarAttendeeInput = {
  email: string
  displayName?: string
  optional?: boolean
  resource?: boolean
}

export function getCalendarEvents(params: {
  timeMin?: string
  timeMax?: string
  query?: string
  pageToken?: string
} = {}): Promise<{
  events: CalendarEvent[]
  next_page_token?: string | null
  next_sync_token?: string | null
}> {
  const search = new URLSearchParams()
  if (params.timeMin) search.set("time_min", params.timeMin)
  if (params.timeMax) search.set("time_max", params.timeMax)
  if (params.query?.trim()) search.set("query", params.query.trim())
  if (params.pageToken) search.set("page_token", params.pageToken)
  search.set("max_results", "100")
  search.set("single_events", "true")
  search.set("order_by", "startTime")

  return apiRequestWithRefresh<{
    events: CalendarEvent[]
    next_page_token?: string | null
    next_sync_token?: string | null
  }>(`/integrations/google/calendar/events?${search.toString()}`)
}

export function createCalendarEvent(
  payload: {
    summary: string
    description?: string
    location?: string
    start: CalendarEventBoundary
    end: CalendarEventBoundary
    attendees?: CalendarAttendeeInput[]
  },
  sendUpdates: CalendarSendUpdates = "all",
): Promise<CalendarEvent> {
  const headers: Record<string, string> = {
    ...jsonHeaders,
    "Idempotency-Key": crypto.randomUUID(),
  }

  return apiRequestWithRefresh<CalendarEvent>(
    `/integrations/google/calendar/events?send_updates=${encodeURIComponent(sendUpdates)}`,
    {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    },
  )
}

export function updateCalendarEvent(
  eventId: string,
  payload: {
    summary?: string
    description?: string
    location?: string
    start?: CalendarEventBoundary
    end?: CalendarEventBoundary
    attendees?: CalendarAttendeeInput[]
  },
  sendUpdates: CalendarSendUpdates = "all",
): Promise<CalendarEvent> {
  return apiRequestWithRefresh<CalendarEvent>(
    `/integrations/google/calendar/events/${encodeURIComponent(eventId)}?send_updates=${encodeURIComponent(sendUpdates)}`,
    {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    },
  )
}

export function deleteCalendarEvent(
  eventId: string,
  sendUpdates: CalendarSendUpdates = "all",
): Promise<{ deleted: boolean; event_id: string }> {
  return apiRequestWithRefresh<{ deleted: boolean; event_id: string }>(
    `/integrations/google/calendar/events/${encodeURIComponent(eventId)}?send_updates=${encodeURIComponent(sendUpdates)}`,
    { method: "DELETE" },
  )
}

export function disconnectCalendar(): Promise<void> {
  return apiRequestWithRefresh<void>("/integrations/google/calendar", {
    method: "DELETE",
  })
}

export function getActivity(params: {
  limit?: number
  eventType?: string
  source?: string
  since?: string
} = {}): Promise<ActivityEvent[]> {
  const search = new URLSearchParams()
  search.set("limit", String(params.limit ?? 80))
  if (params.eventType?.trim()) search.set("event_type", params.eventType.trim())
  if (params.source?.trim()) search.set("source", params.source.trim())
  if (params.since) search.set("since", params.since)
  return apiRequestWithRefresh<ActivityEvent[]>(`/activity?${search.toString()}`)
}

export function getMemories(params: {
  category?: string
  importance?: string
} = {}): Promise<Memory[]> {
  const search = new URLSearchParams()
  search.set("limit", "100")
  if (params.category) search.set("category", params.category)
  if (params.importance) search.set("importance", params.importance)
  const suffix = search.toString()
  return apiRequestWithRefresh<Memory[]>(`/memories?${suffix}`)
}

export function searchMemories(query: string): Promise<MemorySearchResult[]> {
  return apiRequestWithRefresh<MemorySearchResult[]>(
    `/memories/search?query=${encodeURIComponent(query)}&threshold=0.65&limit=20`,
  )
}

export function updateMemory(
  memoryId: number,
  payload: { memory: string; category?: Memory["category"]; importance?: Memory["importance"] },
): Promise<Memory> {
  return apiRequestWithRefresh<Memory>(`/memories/${memoryId}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export function deleteMemory(memoryId: number): Promise<void> {
  return apiRequestWithRefresh<void>(`/memories/${memoryId}`, {
    method: "DELETE",
  })
}

export function getKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
  return apiRequestWithRefresh<KnowledgeDocument[]>("/knowledge/documents?limit=100")
}

export function createKnowledgeDocument(payload: {
  title: string
  content: string
  source?: string | null
}): Promise<KnowledgeDocument> {
  return apiRequestWithRefresh<KnowledgeDocument>("/knowledge/documents", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export function createKnowledgeUrl(url: string): Promise<KnowledgeDocument> {
  return apiRequestWithRefresh<KnowledgeDocument>("/knowledge/urls", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ url }),
  })
}

export function searchKnowledge(query: string): Promise<KnowledgeSearchResult[]> {
  return apiRequestWithRefresh<KnowledgeSearchResult[]>(
    `/knowledge/search?query=${encodeURIComponent(query)}&limit=20`,
  )
}

export function getKnowledgeDocument(documentId: number): Promise<KnowledgeDocumentDetail> {
  return apiRequestWithRefresh<KnowledgeDocumentDetail>(
    `/knowledge/documents/${documentId}`,
  )
}

export function deleteKnowledgeDocument(documentId: number): Promise<void> {
  return apiRequestWithRefresh<void>(`/knowledge/documents/${documentId}`, {
    method: "DELETE",
  })
}

export function getPendingConfirmations(): Promise<Confirmation[]> {
  return apiRequestWithRefresh<Confirmation[]>("/confirmations")
}

export function approveAndExecuteConfirmation(
  confirmationId: number,
): Promise<ConfirmationExecution> {
  return apiRequestWithRefresh<ConfirmationExecution>(
    `/confirmations/${confirmationId}/approve-and-execute`,
    { method: "POST" },
  )
}

export function rejectConfirmation(confirmationId: number): Promise<Confirmation> {
  return apiRequestWithRefresh<Confirmation>(
    `/confirmations/${confirmationId}/reject`,
    { method: "POST" },
  )
}

export function getPermissions(): Promise<Permission[]> {
  return apiRequestWithRefresh<Permission[]>("/permissions")
}

export function setPermission(
  tool: string,
  action: Permission["action"],
  mode: Permission["mode"],
): Promise<Permission> {
  return apiRequestWithRefresh<Permission>(
    `/permissions/${encodeURIComponent(tool)}/${encodeURIComponent(action)}`,
    {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify({ mode }),
    },
  )
}

export function deletePermission(tool: string, action: Permission["action"]): Promise<void> {
  return apiRequestWithRefresh<void>(
    `/permissions/${encodeURIComponent(tool)}/${encodeURIComponent(action)}`,
    { method: "DELETE" },
  )
}

export function getWorkflows(): Promise<Workflow[]> {
  return apiRequestWithRefresh<Workflow[]>("/workflows?limit=80")
}

export function cancelWorkflow(workflowId: number): Promise<{ action: string; updated: boolean }> {
  return apiRequestWithRefresh<{ action: string; updated: boolean }>(
    `/workflows/${workflowId}/cancel`,
    { method: "POST" },
  )
}

export function getNotificationPreferences(userId: string): Promise<NotificationPreferences> {
  return apiRequestWithRefresh<NotificationPreferences>(
    `/users/${encodeURIComponent(userId)}/notification-preferences`,
  )
}

export function updateNotificationPreferences(
  userId: string,
  payload: Partial<Pick<
    NotificationPreferences,
    "timezone" | "daily_activity_digest_enabled" | "delivery_hour" | "delivery_minute"
  >>,
): Promise<NotificationPreferences> {
  return apiRequestWithRefresh<NotificationPreferences>(
    `/users/${encodeURIComponent(userId)}/notification-preferences`,
    {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    },
  )
}

export function getNotificationDestinations(): Promise<NotificationDestination[]> {
  return apiRequestWithRefresh<NotificationDestination[]>("/notification-destinations")
}

export function createNotificationDestination(payload: {
  channel: string
  destination: string
  label?: string
  is_default?: boolean
}): Promise<NotificationDestination> {
  return apiRequestWithRefresh<NotificationDestination>("/notification-destinations", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(payload),
  })
}

export function setDefaultNotificationDestination(
  destinationId: number,
): Promise<NotificationDestination> {
  return apiRequestWithRefresh<NotificationDestination>(
    `/notification-destinations/${destinationId}/default`,
    { method: "POST" },
  )
}

export function deleteNotificationDestination(destinationId: number): Promise<void> {
  return apiRequestWithRefresh<void>(`/notification-destinations/${destinationId}`, {
    method: "DELETE",
  })
}
