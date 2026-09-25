import { useCallback, useEffect, useState, type FormEvent } from "react"

import { ApiRequestError } from "../api/client"
import {
  createCalendarEvent,
  deleteCalendarEvent,
  disconnectCalendar,
  getCalendarConnectUrl,
  getCalendarEvents,
  getCalendarStatus,
  updateCalendarEvent,
  type CalendarEvent,
} from "../api/workspace"
import { Icon } from "../components/Icon"

function formatDate(value: string | undefined): string {
  if (!value) return "Unknown time"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date)
}

function boundary(event: CalendarEvent | null, key: "start" | "end"): string | undefined {
  const value = event?.[key]
  return typeof value === "object" && value !== null && "dateTime" in value ? String((value as { dateTime?: unknown }).dateTime) : undefined
}

function localInput(value: string | undefined): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function isoValue(value: string): string {
  return new Date(value).toISOString()
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
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [form, setForm] = useState({ summary: "", description: "", location: "", start: "", end: "" })
  const [edit, setEdit] = useState({ summary: "", description: "", location: "", start: "", end: "" })

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const status = await getCalendarStatus()
      setConnected(status.connected)
      setCalendarId(status.connection?.calendar_id ?? null)
      if (status.connected) {
        const start = new Date()
        const end = new Date()
        end.setDate(end.getDate() + 30)
        const result = await getCalendarEvents({ timeMin: start.toISOString(), timeMax: end.toISOString(), query: query || undefined })
        setEvents(result.events)
      } else {
        setEvents([])
      }
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
      setError("Google Calendar authorization opened in a new tab. Complete it there, then refresh this page.")
    } catch (err) {
      setError(errorText(err, "NOVA could not start Google Calendar authorization."))
    } finally {
      setWorking(false)
    }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!form.summary.trim() || !form.start || !form.end || working) return
    if (new Date(form.end) <= new Date(form.start)) {
      setError("Event end time must be after the start time.")
      return
    }
    setWorking(true)
    setError(null)
    try {
      await createCalendarEvent({
        summary: form.summary.trim(),
        description: form.description.trim() || undefined,
        location: form.location.trim() || undefined,
        start: { dateTime: isoValue(form.start) },
        end: { dateTime: isoValue(form.end) },
      })
      setForm({ summary: "", description: "", location: "", start: "", end: "" })
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not create that calendar event."))
    } finally {
      setWorking(false)
    }
  }

  const selectEvent = (event: CalendarEvent) => {
    setSelected(event)
    setEdit({
      summary: typeof event.summary === "string" ? event.summary : "",
      description: typeof event.description === "string" ? event.description : "",
      location: typeof event.location === "string" ? event.location : "",
      start: localInput(boundary(event, "start")),
      end: localInput(boundary(event, "end")),
    })
  }

  const saveEvent = async () => {
    if (!selected?.id || !edit.summary.trim() || !edit.start || !edit.end || working) return
    if (new Date(edit.end) <= new Date(edit.start)) {
      setError("Event end time must be after the start time.")
      return
    }
    setWorking(true)
    setError(null)
    try {
      await updateCalendarEvent(selected.id, {
        summary: edit.summary.trim(),
        description: edit.description.trim(),
        location: edit.location.trim(),
        start: { dateTime: isoValue(edit.start) },
        end: { dateTime: isoValue(edit.end) },
      })
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
      await deleteCalendarEvent(selected.id)
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
          <p>Connect Google Calendar, inspect the next 30 days, and create or update events without leaving your workspace.</p>
        </div>
        <div className={connected ? "connection-card connected" : "connection-card"}>
          <span>{connected ? "Connected" : "Not connected"}</span>
          <strong>{connected ? "Google Calendar" : "Google Calendar"}</strong>
          {calendarId && <small>{calendarId}</small>}
        </div>
      </section>

      {!connected ? (
        <section className="resource-panel integration-panel">
          <div className="resource-panel-head"><div><div className="section-kicker">INTEGRATION</div><h2>Connect your calendar.</h2></div></div>
          <p className="resource-muted">NOVA will use the backend's Google OAuth flow. Your browser will handle Google's authorization page.</p>
          <button className="primary-action" type="button" disabled={working} onClick={() => void connect()}><Icon name="calendar" size={17} />Connect Google Calendar</button>
        </section>
      ) : (
        <>
          <section className="resource-panel">
            <div className="resource-panel-head">
              <div><div className="section-kicker">UPCOMING</div><h2>Next 30 days.</h2></div>
              <div className="resource-toolbar"><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search events…" /><button className="secondary-action compact" type="button" onClick={() => void load()}>Refresh</button><button className="danger-action compact" type="button" onClick={() => void disconnect()}>Disconnect</button></div>
            </div>
            {loading ? <div className="resource-loading">Loading calendar…</div> : events.length === 0 ? <div className="resource-empty inline-empty"><Icon name="calendar" size={20} /><span>No upcoming events found.</span></div> : (
              <div className="calendar-event-list">
                {events.map((item) => (
                  <button className={selected?.id === item.id ? "calendar-event selected" : "calendar-event"} key={String(item.id)} type="button" onClick={() => selectEvent(item)}>
                    <span className="calendar-event-date">{formatDate(boundary(item, "start"))}</span>
                    <span><strong>{typeof item.summary === "string" && item.summary ? item.summary : "(Untitled event)"}</strong><small>{typeof item.location === "string" && item.location ? item.location : "No location"}</small></span>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="resource-two-column">
            <div className="resource-panel">
              <div className="resource-panel-head"><div><div className="section-kicker">NEW EVENT</div><h2>Schedule something.</h2></div></div>
              <form className="resource-form" onSubmit={submit}>
                <label className="field"><span>Title</span><input value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} maxLength={300} required /></label>
                <div className="field-grid"><label className="field"><span>Start</span><input type="datetime-local" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} required /></label><label className="field"><span>End</span><input type="datetime-local" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} required /></label></div>
                <label className="field"><span>Location</span><input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} /></label>
                <label className="field"><span>Description</span><textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
                <button className="primary-action" type="submit" disabled={working}><Icon name="plus" size={16} />Create event</button>
              </form>
            </div>

            {selected ? (
              <div className="resource-panel">
                <div className="resource-panel-head"><div><div className="section-kicker">EDIT EVENT</div><h2>{selected.summary as string || "Calendar event"}</h2></div><button className="icon-action" type="button" onClick={() => setSelected(null)} aria-label="Close event editor">×</button></div>
                <div className="resource-form">
                  <label className="field"><span>Title</span><input value={edit.summary} onChange={(e) => setEdit({ ...edit, summary: e.target.value })} /></label>
                  <div className="field-grid"><label className="field"><span>Start</span><input type="datetime-local" value={edit.start} onChange={(e) => setEdit({ ...edit, start: e.target.value })} /></label><label className="field"><span>End</span><input type="datetime-local" value={edit.end} onChange={(e) => setEdit({ ...edit, end: e.target.value })} /></label></div>
                  <label className="field"><span>Location</span><input value={edit.location} onChange={(e) => setEdit({ ...edit, location: e.target.value })} /></label>
                  <label className="field"><span>Description</span><textarea value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></label>
                  <div className="resource-actions"><button className="primary-action compact" type="button" disabled={working} onClick={() => void saveEvent()}>Save event</button><button className="danger-action compact" type="button" disabled={working} onClick={() => void removeEvent()}>Delete</button></div>
                </div>
              </div>
            ) : <div className="resource-empty document-preview"><Icon name="calendar" size={22} /><h3>Select an event.</h3><p>Choose an upcoming event to edit or delete it.</p></div>}
          </section>
        </>
      )}

      {error && <div className="resource-error" role="alert">{error}<button type="button" onClick={() => void load()}>Retry</button></div>}
    </div>
  )
}
