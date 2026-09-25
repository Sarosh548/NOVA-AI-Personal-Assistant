import { useCallback, useEffect, useState, type Dispatch, type FormEvent, type SetStateAction } from "react"

import { ApiRequestError } from "../api/client"
import {
  createCalendarEvent,
  deleteCalendarEvent,
  disconnectCalendar,
  getCalendarConnectUrl,
  getCalendarEvents,
  getCalendarStatus,
  updateCalendarEvent,
  type CalendarAttendeeInput,
  type CalendarEvent,
  type CalendarSendUpdates,
} from "../api/workspace"
import { Icon } from "../components/Icon"

type EventMode = "timed" | "all-day"

type EventForm = {
  summary: string
  description: string
  location: string
  mode: EventMode
  start: string
  end: string
  attendees: string
  sendUpdates: CalendarSendUpdates
}

const sendUpdateOptions: Array<[CalendarSendUpdates, string]> = [
  ["all", "All attendees"],
  ["externalOnly", "External attendees only"],
  ["none", "Do not notify attendees"],
]

function pad(value: number): string {
  return String(value).padStart(2, "0")
}

function dateInputValue(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function dateTimeInputValue(date: Date): string {
  return `${dateInputValue(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function defaultEventForm(): EventForm {
  const start = new Date()
  start.setSeconds(0, 0)
  start.setMinutes(Math.ceil(start.getMinutes() / 15) * 15)
  const end = new Date(start.getTime() + 60 * 60 * 1000)

  return {
    summary: "",
    description: "",
    location: "",
    mode: "timed",
    start: dateTimeInputValue(start),
    end: dateTimeInputValue(end),
    attendees: "",
    sendUpdates: "all",
  }
}

function formatEventTime(event: CalendarEvent | null): string {
  if (!event) return "Unknown time"

  const start = event.start
  const end = event.end

  if (
    typeof start?.date === "string" &&
    typeof end?.date === "string"
  ) {
    const startDate = new Date(`${start.date}T00:00:00`)
    const endDate = new Date(`${end.date}T00:00:00`)
    if (!Number.isNaN(startDate.getTime()) && !Number.isNaN(endDate.getTime())) {
      endDate.setDate(endDate.getDate() - 1)
      const startText = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(startDate)
      const endText = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(endDate)
      return startText === endText ? `All day · ${startText}` : `All day · ${startText} – ${endText}`
    }
  }

  if (typeof start?.dateTime === "string") {
    const startDate = new Date(start.dateTime)
    if (Number.isNaN(startDate.getTime())) return start.dateTime

    if (typeof end?.dateTime === "string") {
      const endDate = new Date(end.dateTime)
      if (!Number.isNaN(endDate.getTime())) {
        return `${new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(startDate)} – ${new Intl.DateTimeFormat(undefined, { timeStyle: "short" }).format(endDate)}`
      }
    }

    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(startDate)
  }

  return "Unknown time"
}

function formatBoundaryDate(event: CalendarEvent): string {
  const value = event.start?.date
  if (!value) return formatEventTime(event)
  const date = new Date(`${value}T00:00:00`)
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date)
}

function timedBoundary(event: CalendarEvent | null, key: "start" | "end"): string {
  const value = event?.[key]
  if (!value || typeof value !== "object" || !("dateTime" in value)) return ""
  const raw = (value as { dateTime?: unknown }).dateTime
  return typeof raw === "string" ? raw : ""
}

function allDayBoundary(event: CalendarEvent | null, key: "start" | "end"): string {
  const value = event?.[key]
  if (!value || typeof value !== "object" || !("date" in value)) return ""
  const raw = (value as { date?: unknown }).date
  return typeof raw === "string" ? raw : ""
}

function localInput(value: string): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  return dateTimeInputValue(date)
}

function inclusiveEndDate(value: string): string {
  if (!value) return ""
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  date.setDate(date.getDate() - 1)
  return dateInputValue(date)
}

function exclusiveEndDate(value: string): string {
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  date.setDate(date.getDate() + 1)
  return dateInputValue(date)
}

function isoValue(value: string): string {
  return new Date(value).toISOString()
}

function parseAttendees(value: string): CalendarAttendeeInput[] {
  const seen = new Set<string>()
  const result: CalendarAttendeeInput[] = []

  for (const token of value.split(/[;,\n]/)) {
    const email = token.trim().toLowerCase()
    if (!email || seen.has(email)) continue
    seen.add(email)
    result.push({ email })
  }

  return result
}

function attendeeText(event: CalendarEvent): string {
  return (event.attendees ?? [])
    .map((attendee) => attendee.email)
    .filter((email): email is string => Boolean(email))
    .join(", ")
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiRequestError ? error.detail : fallback
}

export function CalendarSurface() {
  const [connected, setConnected] = useState(false)
  const [calendarId, setCalendarId] = useState<string | null>(null)
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [selected, setSelected] = useState<CalendarEvent | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [nextPageToken, setNextPageToken] = useState<string | null>(null)
  const [form, setForm] = useState<EventForm>(defaultEventForm())
  const [edit, setEdit] = useState<EventForm>(defaultEventForm())

  const loadEvents = useCallback(async (reset = true) => {
    if (!connected) return

    if (reset) setLoading(true)
    else setLoadingMore(true)

    setError(null)

    try {
      const start = new Date()
      const end = new Date()
      end.setDate(end.getDate() + 30)

      const result = await getCalendarEvents({
        timeMin: start.toISOString(),
        timeMax: end.toISOString(),
        query: query || undefined,
        pageToken: reset ? undefined : nextPageToken ?? undefined,
      })

      setEvents((current) => (reset ? result.events : [...current, ...result.events]))
      setNextPageToken(result.next_page_token ?? null)
    } catch (err) {
      setError(errorText(err, "NOVA could not load Google Calendar events."))
    } finally {
      if (reset) setLoading(false)
      else setLoadingMore(false)
    }
  }, [connected, nextPageToken, query])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const status = await getCalendarStatus()
      setConnected(status.connected)
      setCalendarId(status.connection?.calendar_id ?? null)

      if (!status.connected) {
        setEvents([])
        setNextPageToken(null)
        return
      }

      const start = new Date()
      const end = new Date()
      end.setDate(end.getDate() + 30)

      const result = await getCalendarEvents({
        timeMin: start.toISOString(),
        timeMax: end.toISOString(),
        query: query || undefined,
      })

      setEvents(result.events)
      setNextPageToken(result.next_page_token ?? null)
    } catch (err) {
      setError(errorText(err, "NOVA could not load Google Calendar."))
    } finally {
      setLoading(false)
    }
  }, [query])

  useEffect(() => {
    void load()
  }, [load])

  const connect = async () => {
    setWorking(true)
    setError(null)

    try {
      const result = await getCalendarConnectUrl()
      window.open(result.authorization_url, "_blank", "noopener,noreferrer")
      setError(
        "Google Calendar authorization opened in a new tab. Complete it there, then refresh this page.",
      )
    } catch (err) {
      setError(
        errorText(err, "NOVA could not start Google Calendar authorization."),
      )
    } finally {
      setWorking(false)
    }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!form.summary.trim() || working) return

    const attendees = parseAttendees(form.attendees)

    if (form.mode === "timed") {
      if (!form.start || !form.end) {
        setError("Choose both a start and end time.")
        return
      }

      if (new Date(form.end) <= new Date(form.start)) {
        setError("Event end time must be after the start time.")
        return
      }
    } else if (!form.start || !form.end) {
      setError("Choose both a start and end date.")
      return
    } else if (form.end < form.start) {
      setError("Event end date must be on or after the start date.")
      return
    }

    setWorking(true)
    setError(null)

    try {
      await createCalendarEvent(
        {
          summary: form.summary.trim(),
          description: form.description.trim() || undefined,
          location: form.location.trim() || undefined,
          ...(form.mode === "timed"
            ? {
                start: { dateTime: isoValue(form.start) },
                end: { dateTime: isoValue(form.end) },
              }
            : {
                start: { date: form.start },
                end: { date: exclusiveEndDate(form.end) },
              }),
          ...(attendees.length > 0 ? { attendees } : {}),
        },
        form.sendUpdates,
      )

      setForm(defaultEventForm())
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not create that calendar event."))
    } finally {
      setWorking(false)
    }
  }

  const selectEvent = (event: CalendarEvent) => {
    const allDay = Boolean(event.start?.date)

    setSelected(event)
    setEdit({
      summary: typeof event.summary === "string" ? event.summary : "",
      description: typeof event.description === "string" ? event.description : "",
      location: typeof event.location === "string" ? event.location : "",
      mode: allDay ? "all-day" : "timed",
      start: allDay
        ? allDayBoundary(event, "start")
        : localInput(timedBoundary(event, "start")),
      end: allDay
        ? inclusiveEndDate(allDayBoundary(event, "end"))
        : localInput(timedBoundary(event, "end")),
      attendees: attendeeText(event),
      sendUpdates: "all",
    })
  }

  const saveEvent = async () => {
    if (!selected?.id || !edit.summary.trim() || working) return

    const attendees = parseAttendees(edit.attendees)

    if (edit.mode === "timed") {
      if (!edit.start || !edit.end) {
        setError("Choose both a start and end time.")
        return
      }

      if (new Date(edit.end) <= new Date(edit.start)) {
        setError("Event end time must be after the start time.")
        return
      }
    } else if (!edit.start || !edit.end) {
      setError("Choose both a start and end date.")
      return
    } else if (edit.end < edit.start) {
      setError("Event end date must be on or after the start date.")
      return
    }

    setWorking(true)
    setError(null)

    try {
      await updateCalendarEvent(
        selected.id,
        {
          summary: edit.summary.trim(),
          description: edit.description.trim() || undefined,
          location: edit.location.trim() || undefined,
          ...(edit.mode === "timed"
            ? {
                start: { dateTime: isoValue(edit.start) },
                end: { dateTime: isoValue(edit.end) },
              }
            : {
                start: { date: edit.start },
                end: { date: exclusiveEndDate(edit.end) },
              }),
          attendees,
        },
        edit.sendUpdates,
      )

      setSelected(null)
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not update that event."))
    } finally {
      setWorking(false)
    }
  }

  const removeEvent = async () => {
    if (!selected?.id || working || !window.confirm("Delete this Google Calendar event?")) return

    setWorking(true)
    setError(null)

    try {
      await deleteCalendarEvent(selected.id, edit.sendUpdates)
      setSelected(null)
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not delete that event."))
    } finally {
      setWorking(false)
    }
  }

  const disconnect = async () => {
    if (working || !window.confirm("Disconnect Google Calendar from NOVA?")) return

    setWorking(true)
    setError(null)

    try {
      await disconnectCalendar()
      setConnected(false)
      setCalendarId(null)
      setEvents([])
      setNextPageToken(null)
      setSelected(null)
    } catch (err) {
      setError(errorText(err, "NOVA could not disconnect Google Calendar."))
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className="content-shell resource-shell">
      <section className="resource-hero">
        <div>
          <div className="section-kicker">CALENDAR</div>
          <h1>Bring your schedule into NOVA.</h1>
          <p>
            Connect Google Calendar, inspect the next 30 days, and manage timed,
            all-day, and attendee-aware events without leaving your workspace.
          </p>
        </div>

        <div className={connected ? "connection-card connected" : "connection-card"}>
          <span>{connected ? "Connected" : "Not connected"}</span>
          <strong>Google Calendar</strong>
          {calendarId && <small>{calendarId}</small>}
        </div>
      </section>

      {!connected ? (
        <section className="resource-panel integration-panel">
          <div className="resource-panel-head">
            <div>
              <div className="section-kicker">INTEGRATION</div>
              <h2>Connect your calendar.</h2>
            </div>
          </div>
          <p className="resource-muted">
            NOVA will use the backend's Google OAuth flow. Your browser will
            handle Google's authorization page.
          </p>
          <button
            className="primary-action"
            type="button"
            disabled={working}
            onClick={() => void connect()}
          >
            <Icon name="calendar" size={17} />
            Connect Google Calendar
          </button>
        </section>
      ) : (
        <>
          <section className="resource-panel">
            <div className="resource-panel-head">
              <div>
                <div className="section-kicker">UPCOMING</div>
                <h2>Next 30 days.</h2>
              </div>
              <div className="resource-toolbar">
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search events…"
                  aria-label="Search calendar events"
                />
                <button
                  className="secondary-action compact"
                  type="button"
                  disabled={loading}
                  onClick={() => void load()}
                >
                  Refresh
                </button>
                <button
                  className="danger-action compact"
                  type="button"
                  disabled={working}
                  onClick={() => void disconnect()}
                >
                  Disconnect
                </button>
              </div>
            </div>

            {loading ? (
              <div className="resource-loading">Loading calendar…</div>
            ) : events.length === 0 ? (
              <div className="resource-empty inline-empty">
                <Icon name="calendar" size={20} />
                <span>No upcoming events found.</span>
              </div>
            ) : (
              <>
                <div className="calendar-event-list">
                  {events.map((item) => (
                    <button
                      className={
                        selected?.id === item.id
                          ? "calendar-event selected"
                          : "calendar-event"
                      }
                      key={String(item.id)}
                      type="button"
                      onClick={() => selectEvent(item)}
                    >
                      <span className="calendar-event-date">
                        {item.start?.date
                          ? formatBoundaryDate(item)
                          : formatEventTime(item)}
                      </span>
                      <span>
                        <strong>
                          {typeof item.summary === "string" && item.summary
                            ? item.summary
                            : "(Untitled event)"}
                        </strong>
                        <small>
                          {item.start?.date
                            ? "All day"
                            : typeof item.location === "string" &&
                                item.location
                              ? item.location
                              : "No location"}
                        </small>
                      </span>
                    </button>
                  ))}
                </div>

                {nextPageToken && (
                  <div className="calendar-load-more">
                    <button
                      className="secondary-action"
                      type="button"
                      disabled={loadingMore}
                      onClick={() => void loadEvents(false)}
                    >
                      {loadingMore ? "Loading more…" : "Load more events"}
                    </button>
                  </div>
                )}
              </>
            )}
          </section>

          <section className="resource-two-column">
            <EventFormPanel
              title="Schedule something."
              kicker="NEW EVENT"
              form={form}
              setForm={setForm}
              working={working}
              onSubmit={submit}
              submitLabel="Create event"
            />

            {selected ? (
              <div className="resource-panel">
                <div className="resource-panel-head">
                  <div>
                    <div className="section-kicker">EVENT DETAILS</div>
                    <h2>
                      {selected.summary || "Calendar event"}
                    </h2>
                  </div>
                  <button
                    className="icon-action"
                    type="button"
                    onClick={() => setSelected(null)}
                    aria-label="Close event editor"
                  >
                    ×
                  </button>
                </div>

                <div className="calendar-event-detail">
                  <div className="calendar-detail-grid">
                    <div>
                      <span>When</span>
                      <strong>{formatEventTime(selected)}</strong>
                    </div>
                    <div>
                      <span>Status</span>
                      <strong>{selected.status || "Scheduled"}</strong>
                    </div>
                  </div>

                  {selected.htmlLink && (
                    <a
                      className="secondary-action compact"
                      href={selected.htmlLink}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open in Google Calendar
                    </a>
                  )}

                  <div className="calendar-attendee-list">
                    <div className="resource-card-kicker">
                      ATTENDEES
                    </div>
                    {selected.attendees?.length ? (
                      selected.attendees.map((attendee, index) => (
                        <div
                          className="calendar-attendee"
                          key={`${attendee.email ?? "attendee"}-${index}`}
                        >
                          <strong>
                            {attendee.displayName || attendee.email || "Guest"}
                          </strong>
                          <small>
                            {attendee.email || "No email"}{" "}
                            {attendee.responseStatus
                              ? `· ${attendee.responseStatus}`
                              : ""}
                          </small>
                        </div>
                      ))
                    ) : (
                      <p className="resource-muted">No attendees.</p>
                    )}
                  </div>
                </div>

                <div className="settings-divider" />

                <div className="resource-form">
                  <label className="field">
                    <span>Title</span>
                    <input
                      value={edit.summary}
                      onChange={(event) =>
                        setEdit({ ...edit, summary: event.target.value })
                      }
                    />
                  </label>

                  <EventModeFields
                    form={edit}
                    setForm={setEdit}
                  />

                  <label className="field">
                    <span>Location</span>
                    <input
                      value={edit.location}
                      onChange={(event) =>
                        setEdit({ ...edit, location: event.target.value })
                      }
                    />
                  </label>

                  <label className="field">
                    <span>Description</span>
                    <textarea
                      value={edit.description}
                      onChange={(event) =>
                        setEdit({ ...edit, description: event.target.value })
                      }
                    />
                  </label>

                  <label className="field">
                    <span>Attendees</span>
                    <textarea
                      value={edit.attendees}
                      onChange={(event) =>
                        setEdit({ ...edit, attendees: event.target.value })
                      }
                      placeholder="person@example.com, another@example.com"
                    />
                    <small className="field-help">
                      Separate email addresses with commas or new lines.
                    </small>
                  </label>

                  <SendUpdatesField
                    value={edit.sendUpdates}
                    onChange={(sendUpdates) =>
                      setEdit({ ...edit, sendUpdates })
                    }
                  />

                  <div className="resource-actions">
                    <button
                      className="primary-action compact"
                      type="button"
                      disabled={working}
                      onClick={() => void saveEvent()}
                    >
                      Save event
                    </button>
                    <button
                      className="danger-action compact"
                      type="button"
                      disabled={working}
                      onClick={() => void removeEvent()}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="resource-empty document-preview">
                <Icon name="calendar" size={22} />
                <h3>Select an event.</h3>
                <p>
                  Choose an upcoming event to inspect its details, attendees,
                  Google Calendar link, or edit it.
                </p>
              </div>
            )}
          </section>
        </>
      )}

      {error && (
        <div className="resource-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}
    </div>
  )
}

function EventFormPanel({
  title,
  kicker,
  form,
  setForm,
  working,
  onSubmit,
  submitLabel,
}: {
  title: string
  kicker: string
  form: EventForm
  setForm: Dispatch<SetStateAction<EventForm>>
  working: boolean
  onSubmit: (event: FormEvent) => Promise<void>
  submitLabel: string
}) {
  return (
    <div className="resource-panel">
      <div className="resource-panel-head">
        <div>
          <div className="section-kicker">{kicker}</div>
          <h2>{title}</h2>
        </div>
      </div>

      <form className="resource-form" onSubmit={(event) => void onSubmit(event)}>
        <label className="field">
          <span>Title</span>
          <input
            value={form.summary}
            onChange={(event) =>
              setForm({ ...form, summary: event.target.value })
            }
            maxLength={300}
            required
          />
        </label>

        <EventModeFields form={form} setForm={setForm} />

        <label className="field">
          <span>Location</span>
          <input
            value={form.location}
            onChange={(event) =>
              setForm({ ...form, location: event.target.value })
            }
          />
        </label>

        <label className="field">
          <span>Description</span>
          <textarea
            value={form.description}
            onChange={(event) =>
              setForm({ ...form, description: event.target.value })
            }
          />
        </label>

        <label className="field">
          <span>Attendees</span>
          <textarea
            value={form.attendees}
            onChange={(event) =>
              setForm({ ...form, attendees: event.target.value })
            }
            placeholder="person@example.com, another@example.com"
          />
          <small className="field-help">
            Separate email addresses with commas or new lines.
          </small>
        </label>

        <SendUpdatesField
          value={form.sendUpdates}
          onChange={(sendUpdates) => setForm({ ...form, sendUpdates })}
        />

        <button
          className="primary-action"
          type="submit"
          disabled={working}
        >
          <Icon name="plus" size={16} />
          {working ? "Saving…" : submitLabel}
        </button>
      </form>
    </div>
  )
}

function EventModeFields({
  form,
  setForm,
}: {
  form: EventForm
  setForm: Dispatch<SetStateAction<EventForm>>
}) {
  return (
    <>
      <label className="toggle-field">
        <input
          type="checkbox"
          checked={form.mode === "all-day"}
          onChange={(event) =>
            setForm({
              ...form,
              mode: event.target.checked ? "all-day" : "timed",
            })
          }
        />
        <span>
          <strong>All-day event</strong>
          <small>Use calendar dates instead of clock times.</small>
        </span>
      </label>

      {form.mode === "all-day" ? (
        <div className="field-grid">
          <label className="field">
            <span>Start date</span>
            <input
              type="date"
              value={form.start}
              onChange={(event) =>
                setForm({ ...form, start: event.target.value })
              }
            />
          </label>
          <label className="field">
            <span>End date</span>
            <input
              type="date"
              value={form.end}
              min={form.start}
              onChange={(event) =>
                setForm({ ...form, end: event.target.value })
              }
            />
          </label>
        </div>
      ) : (
        <div className="field-grid">
          <label className="field">
            <span>Start</span>
            <input
              type="datetime-local"
              value={form.start}
              onChange={(event) =>
                setForm({ ...form, start: event.target.value })
              }
            />
          </label>
          <label className="field">
            <span>End</span>
            <input
              type="datetime-local"
              value={form.end}
              onChange={(event) =>
                setForm({ ...form, end: event.target.value })
              }
            />
          </label>
        </div>
      )}
    </>
  )
}

function SendUpdatesField({
  value,
  onChange,
}: {
  value: CalendarSendUpdates
  onChange: (value: CalendarSendUpdates) => void
}) {
  return (
    <label className="field">
      <span>Attendee notifications</span>
      <select
        value={value}
        onChange={(event) =>
          onChange(event.target.value as CalendarSendUpdates)
        }
      >
        {sendUpdateOptions.map(([option, label]) => (
          <option key={option} value={option}>
            {label}
          </option>
        ))}
      </select>
    </label>
  )
}
