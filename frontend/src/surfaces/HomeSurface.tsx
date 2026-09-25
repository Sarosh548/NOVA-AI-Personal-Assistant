import { useCallback, useEffect, useState } from "react"

import { ApiRequestError } from "../api/client"
import {
  getActivity,
  getPendingConfirmations,
  getReminders,
  getTasks,
  getWorkflows,
} from "../api/workspace"
import { Icon } from "../components/Icon"
import type { SurfaceKey } from "../app/navigation"

type HomeSurfaceProps = {
  onNavigate: (surface: SurfaceKey) => void
}

function formatDate(value: string | null): string {
  if (!value) return "No scheduled time"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "No scheduled time"
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date)
}

function errorText(error: unknown): string {
  return error instanceof ApiRequestError ? error.detail : "NOVA could not refresh the dashboard."
}

export function HomeSurface({ onNavigate }: HomeSurfaceProps) {
  const [taskCount, setTaskCount] = useState(0)
  const [activeTaskCount, setActiveTaskCount] = useState(0)
  const [reminderCount, setReminderCount] = useState(0)
  const [activityCount, setActivityCount] = useState(0)
  const [attentionCount, setAttentionCount] = useState(0)
  const [nextReminder, setNextReminder] = useState<string | null>(null)
  const [latestActivity, setLatestActivity] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setRefreshing(true)
    setError(null)
    try {
      const [tasks, reminders, activity, confirmations, workflows] = await Promise.allSettled([
        getTasks(),
        getReminders(),
        getActivity({ limit: 20 }),
        getPendingConfirmations(),
        getWorkflows(),
      ])
      const failures: string[] = []
      let successfulSources = 0

      if (tasks.status === "fulfilled") {
        successfulSources += 1
        setTaskCount(tasks.value.filter((task) => !["completed", "cancelled"].includes(task.status)).length)
        setActiveTaskCount(tasks.value.filter((task) => task.status === "in_progress").length)
      } else {
        failures.push("tasks")
      }

      if (reminders.status === "fulfilled") {
        successfulSources += 1
        setReminderCount(reminders.value.length)
        setNextReminder(reminders.value[0]?.reminder_time ?? null)
      } else {
        failures.push("reminders")
      }

      if (activity.status === "fulfilled") {
        successfulSources += 1
        setActivityCount(activity.value.length)
        setLatestActivity(activity.value[0]?.title ?? null)
      } else {
        failures.push("activity")
      }

      if (confirmations.status === "fulfilled") {
        successfulSources += 1
      } else {
        failures.push("approvals")
      }

      if (workflows.status === "fulfilled") {
        successfulSources += 1
      } else {
        failures.push("workflows")
      }

      if (confirmations.status === "fulfilled" && workflows.status === "fulfilled") {
        setAttentionCount(
          confirmations.value.length +
            workflows.value.filter((workflow) => !["completed", "cancelled", "failed"].includes(workflow.status)).length,
        )
      }

      if (successfulSources > 0) {
        setLastRefreshedAt(new Date().toISOString())
      }

      if (failures.length > 0) {
        setError(`Some dashboard data could not be refreshed: ${failures.join(", ")}.`)
      }
    } catch (err) {
      setError(errorText(err))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const interval = window.setInterval(() => {
      void refresh()
    }, 30000)
    return () => window.clearInterval(interval)
  }, [refresh])

  return (
    <div className="content-shell home-dashboard">
      <section className="hero-grid dashboard-hero">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" />PERSONAL COMMAND CENTER</div>
          <h1>Your day, with less friction.</h1>
          <p className="hero-copy">NOVA connects conversation, voice, planning, memory, knowledge, and authorized action in one personal workspace.</p>
          <div className="hero-actions">
            <button className="primary-action" type="button" onClick={() => onNavigate("Voice")}><Icon name="mic" size={18} />Start with NOVA</button>
            <button className="secondary-action" type="button" onClick={() => onNavigate("Conversation")}>Open conversation<Icon name="arrow" size={17} /></button>
          </div>
        </div>
        <div className="orb-card dashboard-orb" aria-label="NOVA live status">
          <div className="orb-glow orb-glow-one" /><div className="orb-glow orb-glow-two" />
          <div className="nova-orb"><div className="orb-core"><Icon name="spark" size={34} /></div></div>
          <div className="orb-status"><span className="status-pill">{loading || refreshing ? "Syncing" : "Ready"}</span><span className="orb-caption">Your personal workspace is connected</span></div>
        </div>
      </section>

      <section className="resource-toolbar" aria-label="Dashboard synchronization">
        <div className="resource-toolbar-actions">
          <span className="resource-hint" role="status" aria-live="polite">
            {refreshing
              ? "Refreshing dashboard data…"
              : lastRefreshedAt
                ? `Last synced ${formatDate(lastRefreshedAt)}`
                : "Waiting for dashboard sync"}
          </span>
          <button className="secondary-action compact" type="button" onClick={() => void refresh()} disabled={refreshing}>
            <Icon name="activity" size={15} />{refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </section>

      {error && <div className="resource-error" role="alert">{error}<button type="button" onClick={() => void refresh()} disabled={refreshing}>Retry</button></div>}

      <section className="dashboard-stats">
        <button type="button" className="dashboard-stat-card" onClick={() => onNavigate("Tasks")}><span>Open tasks</span><strong>{loading ? "—" : taskCount}</strong><small>{activeTaskCount} in progress</small></button>
        <button type="button" className="dashboard-stat-card" onClick={() => onNavigate("Reminders")}><span>Pending reminders</span><strong>{loading ? "—" : reminderCount}</strong><small>{nextReminder ? formatDate(nextReminder) : "Nothing scheduled"}</small></button>
        <button type="button" className="dashboard-stat-card" onClick={() => onNavigate("Activity")}><span>Latest activity</span><strong>{loading ? "—" : activityCount}</strong><small>{latestActivity || "No new events"}</small></button>
        <button type="button" className="dashboard-stat-card" onClick={() => onNavigate("Control Center")}><span>Needs attention</span><strong>{loading ? "—" : attentionCount}</strong><small>Pending approvals + active workflows</small></button>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div><div className="section-kicker">QUICK ACTIONS</div><h2>Move from intent to action.</h2></div>
          <span className="section-note">Live workspace</span>
        </div>
        <div className="action-grid">
          <ActionCard icon="mic" title="Talk to NOVA" description="Open the real-time voice workspace." onClick={() => onNavigate("Voice")} />
          <ActionCard icon="check" title="Create a task" description="Capture work with priority and timing." onClick={() => onNavigate("Tasks")} />
          <ActionCard icon="bell" title="Set a reminder" description="Schedule a future follow-up." onClick={() => onNavigate("Reminders")} />
          <ActionCard icon="calendar" title="Plan the day" description="Connect Google Calendar and manage events." onClick={() => onNavigate("Calendar")} />
          <ActionCard icon="brain" title="Review memory" description="Inspect and correct NOVA's personal context." onClick={() => onNavigate("Memory")} />
          <ActionCard icon="book" title="Search knowledge" description="Manage the private retrieval layer." onClick={() => onNavigate("Knowledge")} />
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading"><div><div className="section-kicker">WORKSPACE</div><h2>Everything important, one click away.</h2></div></div>
        <div className="workspace-link-grid">
          <button type="button" onClick={() => onNavigate("Activity")}><Icon name="activity" size={18} /><span><strong>Activity</strong><small>See NOVA's operational trail.</small></span><Icon name="arrow" size={16} /></button>
          <button type="button" onClick={() => onNavigate("Control Center")}><Icon name="settings" size={18} /><span><strong>Control Center</strong><small>Notifications, approvals, permissions, and workflows.</small></span><Icon name="arrow" size={16} /></button>
          <button type="button" onClick={() => onNavigate("Settings")}><Icon name="settings" size={18} /><span><strong>Settings</strong><small>Account and NOVA foundation details.</small></span><Icon name="arrow" size={16} /></button>
        </div>
      </section>
    </div>
  )
}

function ActionCard({
  icon,
  title,
  description,
  onClick,
}: {
  icon: "message" | "mic" | "check" | "bell" | "calendar" | "brain" | "book"
  title: string
  description: string
  onClick: () => void
}) {
  return <button className="action-card" type="button" onClick={onClick}><div className="action-card-icon"><Icon name={icon} size={19} /></div><div className="action-card-content"><div className="action-card-title">{title}</div><div className="action-card-copy">{description}</div></div><Icon name="arrow" size={17} /></button>
}
