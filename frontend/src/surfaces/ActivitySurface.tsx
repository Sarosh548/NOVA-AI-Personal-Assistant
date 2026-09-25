import { useCallback, useEffect, useState } from "react"

import { ApiRequestError } from "../api/client"
import { getActivity, type ActivityEvent } from "../api/workspace"
import { Icon } from "../components/Icon"

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date)
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiRequestError ? error.detail : fallback
}

export function ActivitySurface() {
  const [events, setEvents] = useState<ActivityEvent[]>([])
  const [eventType, setEventType] = useState("")
  const [source, setSource] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setEvents(await getActivity({ eventType: eventType || undefined, source: source || undefined }))
    } catch (err) {
      setError(errorText(err, "NOVA could not load activity."))
    } finally {
      setLoading(false)
    }
  }, [eventType, source])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="content-shell resource-shell">
      <section className="resource-hero">
        <div>
          <div className="section-kicker">ACTIVITY</div>
          <h1>See what NOVA has been doing.</h1>
          <p>A chronological operational trail across conversations, tools, workflows, memory, and notifications.</p>
        </div>
        <div className="resource-stat"><span>Events</span><strong>{events.length}</strong></div>
      </section>

      <section className="resource-panel">
        <div className="resource-panel-head">
          <div><div className="section-kicker">FILTER</div><h2>Focus the timeline.</h2></div>
          <button className="secondary-action compact" type="button" onClick={() => void load()}><Icon name="activity" size={15} />Refresh</button>
        </div>
        <div className="field-grid">
          <label className="field"><span>Event type</span><input value={eventType} onChange={(e) => setEventType(e.target.value)} placeholder="tool_execution" /></label>
          <label className="field"><span>Source</span><input value={source} onChange={(e) => setSource(e.target.value)} placeholder="assistant" /></label>
        </div>
      </section>

      {error && <div className="resource-error" role="alert">{error}<button type="button" onClick={() => void load()}>Retry</button></div>}

      <section className="timeline-list">
        {loading ? <div className="resource-loading">Loading activity…</div> : events.length === 0 ? (
          <div className="resource-empty"><Icon name="activity" size={22} /><h3>No activity found.</h3><p>As NOVA executes work, its operational events will appear here.</p></div>
        ) : events.map((event) => (
          <article className="timeline-item" key={event.id}>
            <div className="timeline-rail"><span /></div>
            <div className="timeline-content">
              <div className="timeline-head">
                <div>
                  <div className="resource-card-kicker">{event.event_type} · {event.source}</div>
                  <h3>{event.title}</h3>
                </div>
                <span className={`status-pill status-${event.status.replace(/[^a-z_]/g, "")}`}>{event.status}</span>
              </div>
              <p>{event.summary}</p>
              <small>{formatDate(event.created_at)}{event.conversation_id ? ` · Conversation #${event.conversation_id}` : ""}{event.workflow_id ? ` · Workflow #${event.workflow_id}` : ""}</small>
            </div>
          </article>
        ))}
      </section>
    </div>
  )
}
