import { useCallback, useEffect, useState, type FormEvent } from "react"

import { ApiRequestError } from "../api/client"
import {
  actOnTask,
  createTask,
  deleteTask,
  getTasks,
  updateTask,
  type Task,
} from "../api/workspace"
import { Icon } from "../components/Icon"

function formatDate(value: string | null): string {
  if (!value) return "No due date"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "No due date"
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

function localInput(value: string | null): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function isoValue(value: string): string | null {
  return value ? new Date(value).toISOString() : null
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiRequestError ? error.detail : fallback
}

export function TasksSurface() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [statusFilter, setStatusFilter] = useState("")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({
    title: "",
    description: "",
    priority: "medium",
    dueAt: "",
  })
  const [edits, setEdits] = useState<Record<number, { priority: string; dueAt: string }>>({})
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await getTasks(statusFilter || undefined)
      setTasks(result)
      setLastRefreshedAt(new Date().toISOString())
      setEdits(
        Object.fromEntries(
          result.map((task) => [
            task.id,
            { priority: task.priority, dueAt: localInput(task.due_at) },
          ]),
        ),
      )
    } catch (err) {
      setError(errorText(err, "NOVA could not load your tasks."))
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    void load()
  }, [load])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!form.title.trim() || creating) return

    setCreating(true)
    setError(null)
    try {
      await createTask({
        title: form.title.trim(),
        description: form.description.trim() || null,
        priority: form.priority,
        due_at: isoValue(form.dueAt),
      })
      setForm({ title: "", description: "", priority: "medium", dueAt: "" })
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not create that task."))
    } finally {
      setCreating(false)
    }
  }

  const mutate = async (taskId: number, action: "start" | "complete" | "cancel" | "delete") => {
    if (busy !== null) return
    if (action === "delete" && !window.confirm("Delete this task permanently?")) return

    setBusy(taskId)
    setError(null)
    try {
      if (action === "delete") {
        await deleteTask(taskId)
      } else {
        await actOnTask(taskId, action)
      }
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not update that task."))
    } finally {
      setBusy(null)
    }
  }

  const saveEdit = async (task: Task) => {
    const edit = edits[task.id]
    if (!edit || busy !== null) return
    setBusy(task.id)
    setError(null)
    try {
      await updateTask(task.id, {
        priority: edit.priority,
        due_at: isoValue(edit.dueAt),
      })
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not save those task changes."))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="content-shell resource-shell">
      <section className="resource-hero">
        <div>
          <div className="section-kicker">TASKS</div>
          <h1>Turn intentions into a queue.</h1>
          <p>Create, prioritize, schedule, start, complete, cancel, or remove tasks from one workspace.</p>
        </div>
        <div className="resource-stat">
          <span>Visible</span>
          <strong>{tasks.length}</strong>
        </div>
      </section>

      <section className="resource-panel">
        <div className="resource-panel-head">
          <div>
            <div className="section-kicker">NEW TASK</div>
            <h2>Capture work for NOVA.</h2>
          </div>
          <div className="resource-toolbar-actions">
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter tasks by status">
              <option value="">All statuses</option>
              <option value="pending">Pending</option>
              <option value="in_progress">In progress</option>
              <option value="completed">Completed</option>
              <option value="cancelled">Cancelled</option>
            </select>
            <button className="secondary-action compact" type="button" onClick={() => void load()} disabled={loading}>
              <Icon name="activity" size={15} />Refresh
            </button>
          </div>
        </div>

        <form className="resource-form" onSubmit={submit}>
          <div className="field-grid field-grid-wide">
            <label className="field field-span-2">
              <span>Title</span>
              <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Prepare tomorrow's client briefing" maxLength={300} required />
            </label>
            <label className="field">
              <span>Priority</span>
              <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </label>
            <label className="field">
              <span>Due</span>
              <input type="datetime-local" value={form.dueAt} onChange={(e) => setForm({ ...form, dueAt: e.target.value })} />
            </label>
            <label className="field field-span-2">
              <span>Description</span>
              <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Optional context or acceptance criteria" maxLength={5000} />
            </label>
          </div>
          <div className="form-actions">
            <button className="primary-action" disabled={creating} type="submit">
              <Icon name="plus" size={17} />
              {creating ? "Creating…" : "Create task"}
            </button>
          </div>
        </form>
      </section>

      {error && <div className="resource-error" role="alert">{error}<button type="button" onClick={() => void load()}>Retry</button></div>}

      <section className="resource-list">
        {loading ? (
          <div className="resource-loading">Loading tasks…</div>
        ) : tasks.length === 0 ? (
          <div className="resource-empty">
            <Icon name="check" size={22} />
            <h3>No tasks here.</h3>
            <p>Create a task above and NOVA will keep its state and timing connected to the backend.</p>
          </div>
        ) : (
          tasks.map((task) => {
            const edit = edits[task.id] ?? { priority: task.priority, dueAt: localInput(task.due_at) }
            return (
              <article className="resource-card" key={task.id}>
                <div className="resource-card-head">
                  <div className="resource-card-title-row">
                    <div>
                      <div className="resource-card-kicker">TASK #{task.id}</div>
                      <h3>{task.title}</h3>
                    </div>
                    <span className={`status-pill status-${task.status.replace(/[^a-z_]/g, "")}`}>{task.status.replace("_", " ")}</span>
                  </div>
                  {task.description && <p className="resource-muted">{task.description}</p>}
                </div>
                <div className="resource-card-body">
                  <div className="task-meta">
                    <div><span>Priority</span><select value={edit.priority} onChange={(e) => setEdits({ ...edits, [task.id]: { ...edit, priority: e.target.value } })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></div>
                    <div><span>Due</span><input type="datetime-local" value={edit.dueAt} onChange={(e) => setEdits({ ...edits, [task.id]: { ...edit, dueAt: e.target.value } })} /></div>
                    <div><span>Created</span><strong>{formatDate(task.created_at)}</strong></div>
                  </div>
                  <div className="resource-actions">
                    <button className="secondary-action compact" type="button" disabled={busy === task.id} onClick={() => void saveEdit(task)}>Save changes</button>
                    {task.status === "pending" && <button className="secondary-action compact" type="button" disabled={busy === task.id} onClick={() => void mutate(task.id, "start")}>Start</button>}
                    {task.status === "in_progress" && <button className="primary-action compact" type="button" disabled={busy === task.id} onClick={() => void mutate(task.id, "complete")}>Complete</button>}
                    {(task.status === "pending" || task.status === "in_progress") && <button className="danger-action compact" type="button" disabled={busy === task.id} onClick={() => void mutate(task.id, "cancel")}>Cancel</button>}
                    <button className="icon-action danger" type="button" aria-label={`Delete task ${task.id}`} disabled={busy === task.id} onClick={() => void mutate(task.id, "delete")}><Icon name="trash" size={15} /></button>
                  </div>
                </div>
              </article>
            )
          })}
          {lastRefreshedAt && (
            <small className="resource-muted sync-caption">
              Last synced {formatDate(lastRefreshedAt)}
            </small>
          )}
        )}
      </section>
    </div>
  )
}
