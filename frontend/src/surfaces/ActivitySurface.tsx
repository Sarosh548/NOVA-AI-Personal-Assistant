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
  const [timeRange, setTimeRange] = useState<"24h" | "7d" | "30d" | "all">("7d")
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null)
  const [operationStatus, setOperationStatus] = useState("")
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setRefreshing(true)
    setError(null)
    try {
      const since =
        timeRange === "24h"
          ? new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
          : timeRange === "7d"
            ? new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
            : timeRange === "30d"
              ? new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString()
              : undefined

      setEvents(
        await getActivity({
          eventType: eventType || undefined,
          source: source || undefined,
          since,
        }),
      )
      setLastSyncedAt(new Date().toISOString())
    } catch (err) {
      setError(errorText(err, "NOVA could not load activity."))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [eventType, source, timeRange])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = window.setInterval(() => {
      void load()
    }, 30000)
    return () => window.clearInterval(interval)
  }, [autoRefresh, load])

  const clearFilters = () => {
    setEventType("")
    setSource("")
    setTimeRange("7d")
    setOperationStatus("Filters cleared.")
  }

  const copyMetadata = async (event: ActivityEvent) => {
    setError(null)
    setOperationStatus("")
    try {
      await navigator.clipboard.writeText(
        JSON.stringify(event.metadata, null, 2),
      )
      setOperationStatus(`Event #${event.id} metadata copied.`)
    } catch {
      setError("NOVA could not copy that event metadata in this browser.")
    }
  }

  const filterSummary = [
    eventType ? `type: ${eventType}` : "",
    source ? `source: ${source}` : "",
    timeRange !== "7d" ? `range: ${timeRange}` : "",
  ].filter(Boolean).join(" · ")

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
          <div className="resource-toolbar-actions">
            <span className="resource-hint" role="status" aria-live="polite">
              {operationStatus
                ? operationStatus
                : refreshing
                  ? "Refreshing activity…"
                  : lastSyncedAt
                    ? `Last synced ${formatDate(lastSyncedAt)}`
                    : "Activity sync pending"}
            </span>
            <label className="inline-select">
              <span>Range</span>
              <select value={timeRange} onChange={(event) => setTimeRange(event.target.value as typeof timeRange)}>
                <option value="24h">24 hours</option>
                <option value="7d">7 days</option>
                <option value="30d">30 days</option>
                <option value="all">All available</option>
              </select>
            </label>
            <label className="toggle-field compact-toggle">
              <input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />
              <span>Auto-refresh</span>
            </label>
            <button className="secondary-action compact" type="button" onClick={() => void load()} disabled={refreshing}>
              <Icon name="activity" size={15} />{refreshing ? "Refreshing…" : "Refresh"}
            </button>
            {(eventType || source || timeRange !== "7d") && (
              <button
                className="ghost-action compact"
                type="button"
                onClick={clearFilters}
              >
                Clear
              </button>
            )}
          </div>
        </div>
        <div className="field-grid">
          <label className="field"><span>Event type</span><input value={eventType} onChange={(e) => setEventType(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void load() }} placeholder="tool_execution" aria-label="Filter activity by event type" /></label>
          <label className="field"><span>Source</span><input value={source} onChange={(e) => setSource(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void load() }} placeholder="assistant" aria-label="Filter activity by source" /></label>
        </div>
        <div className="resource-hint">
          {filterSummary ? `Active filters · ${filterSummary}` : "Showing the default 7-day activity window."}
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
              <details className="timeline-details">
                <summary>View event details</summary>
                <div className="resource-toolbar-actions">
                  <button className="ghost-action compact" type="button" onClick={() => void copyMetadata(event)}>
                    Copy metadata
                  </button>
                </div>
                <pre className="code-block">{JSON.stringify(event.metadata, null, 2)}</pre>
              </details>
            </div>
          </article>
        ))}
      </section>
    </div>
  )
}
