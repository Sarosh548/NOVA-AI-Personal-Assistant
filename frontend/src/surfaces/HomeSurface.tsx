import { parseApiDateTime } from "../app/datetime"
import { useCallback, useEffect, useRef, useState } from "react"

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
  const date = parseApiDateTime(value)
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
  const refreshInFlightRef = useRef(false)

  const refresh = useCallback(async () => {
    if (refreshInFlightRef.current) return

    refreshInFlightRef.current = true
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
      refreshInFlightRef.current = false
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
          <div className="eyebrow"><span className="eyebrow-dot" />YOUR PERSONAL AI EXECUTIVE</div>
          <h1>Your personal executive assistant.</h1>
          <p className="hero-copy">Talk naturally with NOVA, keep your priorities in view, and bring planning, memory, research, and authorized actions into one connected workspace.</p>
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

      <section className="section-block capability-showcase">
        <div className="section-heading capability-heading">
          <div>
            <div className="section-kicker">THE NOVA EXPERIENCE</div>
            <h2>One companion. Every part of your day.</h2>
            <p className="capability-intro">A visual overview of the tools that help NOVA understand, plan, remember, and act with your permission.</p>
          </div>
          <span className="section-note">Personal executive assistant</span>
        </div>

        <div className="capability-grid">
          <button className="capability-card" type="button" onClick={() => onNavigate("Voice")}>
            <div className="capability-art capability-art-voice" aria-hidden="true">
              <div className="capability-orbit capability-orbit-one" />
              <div className="capability-orbit capability-orbit-two" />
              <div className="capability-orbit capability-orbit-three" />
              <div className="capability-orb-core"><Icon name="spark" size={27} /></div>
              <span className="capability-art-label">REAL-TIME VOICE</span>
            </div>
            <div className="capability-card-copy">
              <span className="capability-card-kicker">CONVERSATION</span>
              <h3>Talk naturally</h3>
              <p>A dedicated voice space for talking with NOVA, with a central orb and clear session states.</p>
              <span className="capability-card-link">Open voice <Icon name="arrow" size={15} /></span>
            </div>
          </button>

          <button className="capability-card" type="button" onClick={() => onNavigate("Calendar")}>
            <div className="capability-art capability-art-planner" aria-hidden="true">
              <div className="planner-art-window">
                <div className="planner-art-header"><span>DAILY PLAN</span><span className="planner-art-dots">•••</span></div>
                <div className="planner-art-row"><span className="planner-art-mark" /><span className="planner-art-line long" /></div>
                <div className="planner-art-row"><span className="planner-art-mark accent" /><span className="planner-art-line medium" /></div>
                <div className="planner-art-row"><span className="planner-art-mark" /><span className="planner-art-line short" /></div>
                <div className="planner-art-footer"><span /><span /><span /></div>
              </div>
              <span className="capability-art-label">PLAN WITH CLARITY</span>
            </div>
            <div className="capability-card-copy">
              <span className="capability-card-kicker">PLANNING</span>
              <h3>Make room for what matters</h3>
              <p>Bring calendar events, tasks, and reminders into your planning workflow.</p>
              <span className="capability-card-link">Open calendar <Icon name="arrow" size={15} /></span>
            </div>
          </button>

          <button className="capability-card" type="button" onClick={() => onNavigate("Tasks")}>
            <div className="capability-art capability-art-tasks" aria-hidden="true">
              <div className="tasks-art-panel">
                <div className="tasks-art-top"><span className="tasks-art-symbol"><Icon name="check" size={14} /></span><span className="tasks-art-progress" /></div>
                <div className="tasks-art-item"><i className="done" /><span className="tasks-art-line wide" /></div>
                <div className="tasks-art-item"><i className="done" /><span className="tasks-art-line mid" /></div>
                <div className="tasks-art-item"><i /><span className="tasks-art-line wide" /></div>
                <div className="tasks-art-item"><i /><span className="tasks-art-line narrow" /></div>
              </div>
              <span className="capability-art-label">INTENT → ACTION</span>
            </div>
            <div className="capability-card-copy">
              <span className="capability-card-kicker">EXECUTION</span>
              <h3>Move work forward</h3>
              <p>Capture tasks, track progress, and make the next step clear.</p>
              <span className="capability-card-link">Open tasks <Icon name="arrow" size={15} /></span>
            </div>
          </button>

          <button className="capability-card" type="button" onClick={() => onNavigate("Memory")}>
            <div className="capability-art capability-art-memory" aria-hidden="true">
              <div className="memory-art-line line-a" /><div className="memory-art-line line-b" /><div className="memory-art-line line-c" /><div className="memory-art-line line-d" /><div className="memory-art-line line-e" />
              <span className="memory-art-node node-a" /><span className="memory-art-node node-b" /><span className="memory-art-node node-c" /><span className="memory-art-node node-d" /><span className="memory-art-node node-e" /><span className="memory-art-node node-f" />
              <span className="capability-art-label">PERSONAL CONTEXT</span>
            </div>
            <div className="capability-card-copy">
              <span className="capability-card-kicker">MEMORY</span>
              <h3>Remember what matters</h3>
              <p>Review the preferences, project context, and memories NOVA uses.</p>
              <span className="capability-card-link">Review memory <Icon name="arrow" size={15} /></span>
            </div>
          </button>

          <button className="capability-card" type="button" onClick={() => onNavigate("Conversation")}>
            <div className="capability-art capability-art-research" aria-hidden="true">
              <div className="research-art-sheet">
                <div className="research-art-heading"><span /><span /></div>
                <div className="research-art-rule primary" /><div className="research-art-rule" /><div className="research-art-rule mid" /><div className="research-art-rule short" />
                <div className="research-art-source"><span className="research-art-source-dot" /><span className="research-art-rule mid" /></div>
                <div className="research-art-source"><span className="research-art-source-dot second" /><span className="research-art-rule short" /></div>
              </div>
              <span className="capability-art-label">THINK · RESEARCH · CREATE</span>
            </div>
            <div className="capability-card-copy">
              <span className="capability-card-kicker">KNOWLEDGE & WORK</span>
              <h3>Turn questions into clarity</h3>
              <p>Explore ideas, work through drafts, and ask NOVA to research a topic.</p>
              <span className="capability-card-link">Open conversation <Icon name="arrow" size={15} /></span>
            </div>
          </button>

          <button className="capability-card" type="button" onClick={() => onNavigate("Control Center")}>
            <div className="capability-art capability-art-control" aria-hidden="true">
              <div className="control-art-shield"><Icon name="sliders" size={31} /></div>
              <div className="control-art-chip chip-a"><Icon name="check" size={12} /> APPROVALS</div>
              <div className="control-art-chip chip-b"><Icon name="bell" size={12} /> ALERTS</div>
              <span className="capability-art-label">YOU STAY IN CONTROL</span>
            </div>
            <div className="capability-card-copy">
              <span className="capability-card-kicker">PERMISSIONS & TRUST</span>
              <h3>Keep every action accountable</h3>
              <p>Review approvals, permissions, notifications, and workflow activity.</p>
              <span className="capability-card-link">Open control center <Icon name="arrow" size={15} /></span>
            </div>
          </button>
        </div>
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
