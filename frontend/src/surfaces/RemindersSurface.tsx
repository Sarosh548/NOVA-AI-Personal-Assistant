import { useCallback, useEffect, useState, type FormEvent } from "react"

import { ApiRequestError } from "../api/client"
import {
  actOnReminder,
  createReminder,
  deleteReminder,
  getReminders,
  updateReminder,
  type Reminder,
} from "../api/workspace"
import { Icon } from "../components/Icon"

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date)
}

function localInput(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiRequestError ? error.detail : fallback
}

export function RemindersSurface() {
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ title: "", time: "" })
  const [edits, setEdits] = useState<Record<number, { title: string; time: string }>>({})
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await getReminders()
      setReminders(result)
      setLastRefreshedAt(new Date().toISOString())
      setEdits(
        Object.fromEntries(
          result.map((item) => [item.id, { title: item.title, time: localInput(item.reminder_time) }]),
        ),
      )
    } catch (err) {
      setError(errorText(err, "NOVA could not load your reminders."))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!form.title.trim() || !form.time || creating) return
    setCreating(true)
    setError(null)
    try {
      await createReminder({ title: form.title.trim(), reminder_time: new Date(form.time).toISOString() })
      setForm({ title: "", time: "" })
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not create that reminder."))
    } finally {
      setCreating(false)
    }
  }

  const mutate = async (reminderId: number, action: "complete" | "cancel" | "delete") => {
    if (busy !== null) return
    if (action === "delete" && !window.confirm("Delete this reminder permanently?")) return
    setBusy(reminderId)
    setError(null)
    try {
      if (action === "delete") await deleteReminder(reminderId)
      else await actOnReminder(reminderId, action)
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not update that reminder."))
    } finally {
      setBusy(null)
    }
  }

  const saveEdit = async (reminder: Reminder) => {
    const edit = edits[reminder.id]
    if (!edit || busy !== null || !edit.title.trim() || !edit.time) return
    setBusy(reminder.id)
    setError(null)
    try {
      await updateReminder(reminder.id, {
        title: edit.title.trim(),
        reminder_time: new Date(edit.time).toISOString(),
      })
      await load()
    } catch (err) {
      setError(errorText(err, "NOVA could not save that reminder."))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="content-shell resource-shell">
      <section className="resource-hero">
        <div>
          <div className="section-kicker">REMINDERS</div>
          <h1>Give important moments a time.</h1>
          <p>Manage pending reminders directly against NOVA's durable reminder service.</p>
        </div>
        <div className="resource-stat"><span>Pending</span><strong>{reminders.length}</strong></div>
      </section>

      <section className="resource-panel">
        <div className="resource-panel-head">
          <div><div className="section-kicker">NEW REMINDER</div><h2>Schedule a follow-up.</h2></div>
          <button className="secondary-action compact" type="button" onClick={() => void load()} disabled={loading}>
            <Icon name="activity" size={15} />Refresh
          </button>
        </div>
        <form className="resource-form" onSubmit={submit}>
          <div className="field-grid">
            <label className="field field-span-2"><span>Reminder</span><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Call the client after lunch" maxLength={300} required /></label>
            <label className="field"><span>When</span><input type="datetime-local" value={form.time} onChange={(e) => setForm({ ...form, time: e.target.value })} required /></label>
          </div>
          <div className="form-actions"><button className="primary-action" type="submit" disabled={creating}><Icon name="bell" size={17} />{creating ? "Scheduling…" : "Set reminder"}</button></div>
        </form>
      </section>

      {error && <div className="resource-error" role="alert">{error}<button type="button" onClick={() => void load()}>Retry</button></div>}

      <section className="resource-list">
        {loading ? (
          <div className="resource-loading">Loading reminders…</div>
        ) : reminders.length === 0 ? (
          <div className="resource-empty"><Icon name="bell" size={22} /><h3>No pending reminders.</h3><p>Future follow-ups will appear here as NOVA creates or schedules them.</p></div>
        ) : (
          <>
            {reminders.map((reminder) => {
              const edit = edits[reminder.id] ?? { title: reminder.title, time: localInput(reminder.reminder_time) }
              const dirty =
                edit.title !== reminder.title ||
                (edit.time ? new Date(edit.time).toISOString() : "") !== reminder.reminder_time

              return (
                <article className="resource-card" key={reminder.id}>
                  <div className="resource-card-head">
                    <div className="resource-card-title-row">
                      <div><div className="resource-card-kicker">REMINDER #{reminder.id}</div><h3>{reminder.title}</h3></div>
                      <span className="status-pill status-pending">{reminder.status}</span>
                    </div>
                    <p className="resource-muted">Scheduled for {formatDate(reminder.reminder_time)}</p>
                  </div>
                  <div className="resource-card-body">
                    <div className="field-grid">
                      <label className="field field-span-2"><span>Title</span><input value={edit.title} onChange={(e) => setEdits({ ...edits, [reminder.id]: { ...edit, title: e.target.value } })} /></label>
                      <label className="field"><span>When</span><input type="datetime-local" value={edit.time} onChange={(e) => setEdits({ ...edits, [reminder.id]: { ...edit, time: e.target.value } })} /></label>
                    </div>
                    <div className="resource-actions">
                      <button className="secondary-action compact" type="button" disabled={busy === reminder.id || !dirty} onClick={() => void saveEdit(reminder)}>Save changes</button>
                      <button className="primary-action compact" type="button" disabled={busy === reminder.id} onClick={() => void mutate(reminder.id, "complete")}>Complete</button>
                      <button className="secondary-action compact" type="button" disabled={busy === reminder.id} onClick={() => void mutate(reminder.id, "cancel")}>Cancel</button>
                      <button className="icon-action danger" type="button" aria-label={`Delete reminder ${reminder.id}`} disabled={busy === reminder.id} onClick={() => void mutate(reminder.id, "delete")}><Icon name="trash" size={15} /></button>
                    </div>
                  </div>
                </article>
              )
            })}
            {lastRefreshedAt && (
              <small className="resource-muted sync-caption">Last synced {formatDate(lastRefreshedAt)}</small>
            )}
          </>
        )}
      </section>
    </div>
  )
}
