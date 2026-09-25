import { useCallback, useEffect, useMemo, useState } from "react"

import { ApiRequestError } from "../api/client"
import {
  approveAndExecuteConfirmation,
  cancelWorkflow,
  createNotificationDestination,
  deleteNotificationDestination,
  deletePermission,
  getNotificationDestinations,
  getNotificationPreferences,
  getPendingConfirmations,
  getPermissions,
  getWorkflows,
  rejectConfirmation,
  setDefaultNotificationDestination,
  setPermission,
  updateNotificationPreferences,
  type Confirmation,
  type NotificationDestination,
  type NotificationPreferences,
  type Permission,
  type Workflow,
} from "../api/workspace"
import { Icon } from "../components/Icon"
import { useAuth } from "../auth/AuthProvider"

type SettingsTab = "account" | "notifications" | "safety" | "workflows"

const permissionActions: Permission["action"][] = [
  "list",
  "get",
  "search",
  "send",
  "create",
  "update",
  "start",
  "complete",
  "cancel",
  "delete",
]

function formatDate(value: string | null): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date)
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiRequestError ? error.detail : fallback
}

export function SettingsSurface() {
  const { user } = useAuth()
  const [tab, setTab] = useState<SettingsTab>("account")
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null)
  const [destinations, setDestinations] = useState<NotificationDestination[]>([])
  const [permissions, setPermissions] = useState<Permission[]>([])
  const [confirmations, setConfirmations] = useState<Confirmation[]>([])
  const [workflows, setWorkflows] = useState<Workflow[]>([])

  const load = useCallback(async () => {
    if (!user) return
    setLoading(true)
    setError(null)
    try {
      const [prefs, destinationsResult, permissionsResult, confirmationsResult, workflowsResult] = await Promise.all([
        getNotificationPreferences(user.id),
        getNotificationDestinations(),
        getPermissions(),
        getPendingConfirmations(),
        getWorkflows(),
      ])
      setPreferences(prefs)
      setDestinations(destinationsResult)
      setPermissions(permissionsResult)
      setConfirmations(confirmationsResult)
      setWorkflows(workflowsResult)
    } catch (err) {
      setError(errorText(err, "NOVA could not load settings."))
    } finally {
      setLoading(false)
    }
  }, [user])

  useEffect(() => {
    void load()
  }, [load])

  const pendingWorkflows = useMemo(
    () => workflows.filter((workflow) => !["completed", "cancelled", "failed"].includes(workflow.status)),
    [workflows],
  )

  const updatePref = async (payload: Partial<Pick<NotificationPreferences, "timezone" | "daily_activity_digest_enabled" | "delivery_hour" | "delivery_minute">>) => {
    if (!user || !preferences || working) return
    setWorking(true)
    setError(null)
    try {
      setPreferences(await updateNotificationPreferences(user.id, payload))
    } catch (err) {
      setError(errorText(err, "NOVA could not update notification preferences."))
    } finally {
      setWorking(false)
    }
  }

  const addDestination = async (channel: string, destination: string, label: string, isDefault: boolean) => {
    if (!destination.trim() || working) return
    setWorking(true)
    setError(null)
    try {
      await createNotificationDestination({
        channel,
        destination: destination.trim(),
        label: label.trim() || undefined,
        is_default: isDefault,
      })
      setDestinations(await getNotificationDestinations())
    } catch (err) {
      setError(errorText(err, "NOVA could not add that notification destination."))
    } finally {
      setWorking(false)
    }
  }

  const handleDestinationDelete = async (id: number) => {
    if (working || !window.confirm("Remove this notification destination?")) return
    setWorking(true)
    setError(null)
    try {
      await deleteNotificationDestination(id)
      setDestinations(await getNotificationDestinations())
    } catch (err) {
      setError(errorText(err, "NOVA could not remove that destination."))
    } finally {
      setWorking(false)
    }
  }

  const makeDefault = async (id: number) => {
    if (working) return
    setWorking(true)
    setError(null)
    try {
      await setDefaultNotificationDestination(id)
      setDestinations(await getNotificationDestinations())
    } catch (err) {
      setError(errorText(err, "NOVA could not set that destination as default."))
    } finally {
      setWorking(false)
    }
  }

  const changePermission = async (permission: Permission, mode: Permission["mode"]) => {
    if (working) return
    setWorking(true)
    setError(null)
    try {
      await setPermission(permission.tool, permission.action, mode)
      setPermissions(await getPermissions())
    } catch (err) {
      setError(errorText(err, "NOVA could not update that permission."))
    } finally {
      setWorking(false)
    }
  }

  const removePermission = async (permission: Permission) => {
    if (working || !window.confirm(`Remove ${permission.tool}/${permission.action} permission?`)) return
    setWorking(true)
    setError(null)
    try {
      await deletePermission(permission.tool, permission.action)
      setPermissions(await getPermissions())
    } catch (err) {
      setError(errorText(err, "NOVA could not remove that permission."))
    } finally {
      setWorking(false)
    }
  }

  const resolveConfirmation = async (id: number, action: "approve" | "reject") => {
    if (working) return
    setWorking(true)
    setError(null)
    try {
      if (action === "approve") {
        await approveAndExecuteConfirmation(id)
      } else {
        await rejectConfirmation(id)
      }
      setConfirmations(await getPendingConfirmations())
    } catch (err) {
      setError(errorText(err, "NOVA could not resolve that approval."))
    } finally {
      setWorking(false)
    }
  }

  const stopWorkflow = async (id: number) => {
    if (working || !window.confirm("Cancel this workflow?")) return
    setWorking(true)
    setError(null)
    try {
      await cancelWorkflow(id)
      setWorkflows(await getWorkflows())
    } catch (err) {
      setError(errorText(err, "NOVA could not cancel that workflow."))
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className="content-shell resource-shell settings-shell">
      <section className="resource-hero">
        <div>
          <div className="section-kicker">SETTINGS</div>
          <h1>Control how NOVA works for you.</h1>
          <p>Manage your account context, notifications, safety permissions, approvals, and durable workflows.</p>
        </div>
        <div className="settings-counter">
          <span>Pending approvals</span>
          <strong>{confirmations.length}</strong>
        </div>
      </section>

      <div className="settings-tabs" role="tablist" aria-label="Settings sections">
        {([
          ["account", "Account"],
          ["notifications", "Notifications"],
          ["safety", "Safety & approvals"],
          ["workflows", "Workflows"],
        ] as const).map(([value, label]) => (
          <button key={value} className={tab === value ? "settings-tab active" : "settings-tab"} type="button" role="tab" aria-selected={tab === value} onClick={() => setTab(value)}>
            {label}
          </button>
        ))}
      </div>

      {error && <div className="resource-error" role="alert">{error}<button type="button" onClick={() => void load()}>Retry</button></div>}

      {loading ? <div className="resource-loading">Loading settings…</div> : (
        <>
          {tab === "account" && (
            <section className="resource-two-column">
              <article className="resource-panel">
                <div className="resource-panel-head"><div><div className="section-kicker">ACCOUNT</div><h2>Your NOVA identity.</h2></div></div>
                <div className="settings-profile">
                  <div className="settings-avatar">{(user?.display_name?.[0] || "N").toUpperCase()}</div>
                  <div><span className="resource-card-kicker">DISPLAY NAME</span><strong>{user?.display_name || "NOVA user"}</strong><small>{user?.id}</small></div>
                </div>
                <div className="settings-detail-grid">
                  <div><span>Status</span><strong>{user?.is_active ? "Active" : "Inactive"}</strong></div>
                  <div><span>Created</span><strong>{formatDate(user?.created_at ?? null)}</strong></div>
                  <div><span>Updated</span><strong>{formatDate(user?.updated_at ?? null)}</strong></div>
                </div>
              </article>
              <article className="resource-panel">
                <div className="resource-panel-head"><div><div className="section-kicker">SYSTEM</div><h2>Frontend foundation.</h2></div></div>
                <div className="settings-check-list">
                  <div><Icon name="check" size={16} /><span>Authenticated account session</span><strong>Ready</strong></div>
                  <div><Icon name="check" size={16} /><span>Conversation workspace</span><strong>Ready</strong></div>
                  <div><Icon name="check" size={16} /><span>Realtime voice workspace</span><strong>Ready</strong></div>
                  <div><Icon name="check" size={16} /><span>Task, reminder & calendar controls</span><strong>Ready</strong></div>
                  <div><Icon name="check" size={16} /><span>Memory & private knowledge</span><strong>Ready</strong></div>
                </div>
              </article>
            </section>
          )}

          {tab === "notifications" && preferences && (
            <section className="resource-two-column">
              <article className="resource-panel">
                <div className="resource-panel-head"><div><div className="section-kicker">PREFERENCES</div><h2>Daily delivery.</h2></div></div>
                <div className="field-grid">
                  <label className="field field-span-2"><span>Timezone</span><input value={preferences.timezone} onChange={(e) => setPreferences({ ...preferences, timezone: e.target.value })} onBlur={() => void updatePref({ timezone: preferences.timezone })} /></label>
                  <label className="toggle-field field-span-2"><input type="checkbox" checked={preferences.daily_activity_digest_enabled} onChange={(e) => void updatePref({ daily_activity_digest_enabled: e.target.checked })} /><span><strong>Daily activity digest</strong><small>Let NOVA send the configured proactive daily summary.</small></span></label>
                  <label className="field"><span>Delivery hour</span><input type="number" min={0} max={23} value={preferences.delivery_hour} onChange={(e) => setPreferences({ ...preferences, delivery_hour: Number(e.target.value) })} onBlur={() => void updatePref({ delivery_hour: preferences.delivery_hour })} /></label>
                  <label className="field"><span>Delivery minute</span><input type="number" min={0} max={59} value={preferences.delivery_minute} onChange={(e) => setPreferences({ ...preferences, delivery_minute: Number(e.target.value) })} onBlur={() => void updatePref({ delivery_minute: preferences.delivery_minute })} /></label>
                </div>
                <p className="resource-hint">Changes save directly through NOVA's authenticated notification-preferences API.</p>
              </article>

              <NotificationDestinations
                destinations={destinations}
                working={working}
                onAdd={addDestination}
                onDefault={makeDefault}
                onDelete={handleDestinationDelete}
              />
            </section>
          )}

          {tab === "safety" && (
            <section className="settings-stack">
              <article className="resource-panel">
                <div className="resource-panel-head"><div><div className="section-kicker">APPROVAL QUEUE</div><h2>Actions waiting for you.</h2></div><span className="status-pill">{confirmations.length} pending</span></div>
                {confirmations.length === 0 ? <div className="resource-empty inline-empty"><Icon name="check" size={20} /><span>No pending approvals.</span></div> : (
                  <div className="confirmation-list">
                    {confirmations.map((item) => (
                      <article className="confirmation-card" key={item.id}>
                        <div className="timeline-head"><div><div className="resource-card-kicker">{item.tool} · {item.action}</div><h3>Approval #{item.id}</h3></div><span className="status-pill status-pending">{item.status}</span></div>
                        <p>{item.reason}</p>
                        <pre className="code-block">{JSON.stringify(item.data, null, 2)}</pre>
                        <small>Expires {formatDate(item.expires_at)}</small>
                        <div className="resource-actions"><button className="primary-action compact" type="button" disabled={working} onClick={() => void resolveConfirmation(item.id, "approve")}>Approve & execute</button><button className="danger-action compact" type="button" disabled={working} onClick={() => void resolveConfirmation(item.id, "reject")}>Reject</button></div>
                      </article>
                    ))}
                  </div>
                )}
              </article>

              <article className="resource-panel">
                <div className="resource-panel-head"><div><div className="section-kicker">PERMISSIONS</div><h2>Saved action rules.</h2></div></div>
                <PermissionEditor permissions={permissions} working={working} onChange={changePermission} onDelete={removePermission} />
              </article>
            </section>
          )}

          {tab === "workflows" && (
            <section className="resource-panel">
              <div className="resource-panel-head"><div><div className="section-kicker">DURABLE EXECUTION</div><h2>Workflows and their steps.</h2></div><span className="status-pill">{pendingWorkflows.length} active</span></div>
              {workflows.length === 0 ? <div className="resource-empty inline-empty"><Icon name="activity" size={20} /><span>No workflows have been recorded yet.</span></div> : (
                <div className="workflow-list">
                  {workflows.map((workflow) => (
                    <article className="workflow-card" key={workflow.id}>
                      <div className="timeline-head"><div><div className="resource-card-kicker">WORKFLOW #{workflow.id} · {workflow.execution_mode}</div><h3>{workflow.plan?.title ? String(workflow.plan.title) : `Workflow #${workflow.id}`}</h3></div><span className={`status-pill status-${workflow.status}`}>{workflow.status}</span></div>
                      <p>{workflow.error || (workflow.result ? "Execution produced a result." : "Durable execution is tracked step-by-step by NOVA.")}</p>
                      <div className="workflow-meta"><span>Steps <strong>{workflow.steps.length}</strong></span><span>Created <strong>{formatDate(workflow.created_at)}</strong></span><span>Scheduled <strong>{formatDate(workflow.scheduled_at)}</strong></span></div>
                      <div className="workflow-steps">{workflow.steps.map((step) => <div className="workflow-step" key={step.id}><span>{step.position + 1}</span><div><strong>{step.tool} / {step.action}</strong><small>{step.status} · attempts {step.attempts}</small></div></div>)}</div>
                      {!["completed", "cancelled", "failed"].includes(workflow.status) && <div className="resource-actions"><button className="danger-action compact" type="button" disabled={working} onClick={() => void stopWorkflow(workflow.id)}>Cancel workflow</button></div>}
                    </article>
                  ))}
                </div>
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}

function NotificationDestinations({
  destinations,
  working,
  onAdd,
  onDefault,
  onDelete,
}: {
  destinations: NotificationDestination[]
  working: boolean
  onAdd: (channel: string, destination: string, label: string, isDefault: boolean) => Promise<void>
  onDefault: (id: number) => Promise<void>
  onDelete: (id: number) => Promise<void>
}) {
  const [form, setForm] = useState({ channel: "email", destination: "", label: "", isDefault: false })

  return (
    <article className="resource-panel">
      <div className="resource-panel-head"><div><div className="section-kicker">DESTINATIONS</div><h2>Where NOVA can notify you.</h2></div></div>
      <div className="destination-list">
        {destinations.map((destination) => (
          <div className="destination-row" key={destination.id}>
            <div><span className="resource-card-kicker">{destination.channel}</span><strong>{destination.label || destination.destination}</strong><small>{destination.destination}</small></div>
            <div className="resource-actions">
              {destination.is_default ? <span className="status-pill status-completed">Default</span> : <button className="secondary-action compact" type="button" disabled={working} onClick={() => void onDefault(destination.id)}>Make default</button>}
              <button className="icon-action danger" type="button" disabled={working} onClick={() => void onDelete(destination.id)} aria-label="Remove destination"><Icon name="trash" size={14} /></button>
            </div>
          </div>
        ))}
      </div>
      <div className="settings-divider" />
      <div className="field-grid">
        <label className="field"><span>Channel</span><select value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}><option value="email">Email</option><option value="web">Web</option><option value="sms">SMS</option><option value="push">Push</option><option value="whatsapp">WhatsApp</option></select></label>
        <label className="field"><span>Destination</span><input value={form.destination} onChange={(e) => setForm({ ...form, destination: e.target.value })} placeholder="you@example.com" /></label>
        <label className="field"><span>Label</span><input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="Primary" /></label>
        <label className="toggle-field"><input type="checkbox" checked={form.isDefault} onChange={(e) => setForm({ ...form, isDefault: e.target.checked })} /><span><strong>Set default</strong><small>Use this destination for default delivery.</small></span></label>
      </div>
      <button className="secondary-action" type="button" disabled={working || !form.destination.trim()} onClick={() => { void onAdd(form.channel, form.destination, form.label, form.isDefault); setForm({ channel: "email", destination: "", label: "", isDefault: false }) }}><Icon name="plus" size={15} />Add destination</button>
    </article>
  )
}

function PermissionEditor({
  permissions,
  working,
  onChange,
  onDelete,
}: {
  permissions: Permission[]
  working: boolean
  onChange: (permission: Permission, mode: Permission["mode"]) => Promise<void>
  onDelete: (permission: Permission) => Promise<void>
}) {
  const [form, setForm] = useState<{ tool: string; action: Permission["action"]; mode: Permission["mode"] }>({ tool: "task", action: "create", mode: "confirm" })

  return (
    <div className="permission-area">
      <div className="permission-list">
        {permissions.length === 0 ? <div className="resource-empty inline-empty"><span>No saved permissions. NOVA will use its deterministic safety defaults.</span></div> : permissions.map((permission) => (
          <div className="permission-row" key={`${permission.tool}-${permission.action}`}>
            <div><strong>{permission.tool}</strong><span>/ {permission.action}</span><small>Updated {formatDate(permission.updated_at)}</small></div>
            <div className="resource-actions">
              <select value={permission.mode} disabled={working} onChange={(e) => void onChange(permission, e.target.value as Permission["mode"])}><option value="allow">Allow</option><option value="confirm">Confirm</option><option value="deny">Deny</option></select>
              <button className="icon-action danger" type="button" disabled={working} onClick={() => void onDelete(permission)} aria-label="Remove permission"><Icon name="trash" size={14} /></button>
            </div>
          </div>
        ))}
      </div>
      <div className="settings-divider" />
      <div className="resource-card-kicker">ADD / OVERRIDE RULE</div>
      <div className="field-grid">
        <label className="field"><span>Tool</span><input value={form.tool} onChange={(e) => setForm({ ...form, tool: e.target.value })} placeholder="task" /></label>
        <label className="field"><span>Action</span><select value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value as Permission["action"] })}>{permissionActions.map((action) => <option key={action} value={action}>{action}</option>)}</select></label>
        <label className="field"><span>Mode</span><select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value as Permission["mode"] })}><option value="allow">Allow</option><option value="confirm">Confirm</option><option value="deny">Deny</option></select></label>
        <div className="form-actions"><button className="secondary-action compact" type="button" disabled={working || !form.tool.trim()} onClick={() => { void onChange({ id: 0, tool: form.tool.trim(), action: form.action, mode: form.mode, created_at: "", updated_at: "" }, form.mode) }}>Save rule</button></div>
      </div>
    </div>
  )
}
