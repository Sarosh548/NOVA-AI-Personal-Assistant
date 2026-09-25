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

type ControlTab = "notifications" | "approvals" | "permissions" | "workflows"

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
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiRequestError ? error.detail : fallback
}

export function ControlCenterSurface() {
  const { user } = useAuth()
  const [tab, setTab] = useState<ControlTab>("notifications")
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
      const [
        preferencesResult,
        destinationsResult,
        permissionsResult,
        confirmationsResult,
        workflowsResult,
      ] = await Promise.all([
        getNotificationPreferences(user.id),
        getNotificationDestinations(),
        getPermissions(),
        getPendingConfirmations(),
        getWorkflows(),
      ])

      setPreferences(preferencesResult)
      setDestinations(destinationsResult)
      setPermissions(permissionsResult)
      setConfirmations(confirmationsResult)
      setWorkflows(workflowsResult)
    } catch (err) {
      setError(errorText(err, "NOVA could not load the control center."))
    } finally {
      setLoading(false)
    }
  }, [user])

  useEffect(() => {
    void load()
  }, [load])

  const activeWorkflows = useMemo(
    () =>
      workflows.filter(
        (workflow) =>
          !["completed", "cancelled", "failed"].includes(workflow.status),
      ),
    [workflows],
  )

  const updatePreference = async (
    payload: Partial<
      Pick<
        NotificationPreferences,
        | "timezone"
        | "daily_activity_digest_enabled"
        | "delivery_hour"
        | "delivery_minute"
      >
    >,
  ) => {
    if (!user || !preferences || working) return

    setWorking(true)
    setError(null)

    try {
      setPreferences(await updateNotificationPreferences(user.id, payload))
    } catch (err) {
      setError(errorText(err, "NOVA could not update that preference."))
    } finally {
      setWorking(false)
    }
  }

  const addDestination = async (
    channel: string,
    destination: string,
    label: string,
    isDefault: boolean,
  ) => {
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

  const removeDestination = async (id: number) => {
    if (working || !window.confirm("Remove this notification destination?")) return

    setWorking(true)
    setError(null)

    try {
      await deleteNotificationDestination(id)
      setDestinations(await getNotificationDestinations())
    } catch (err) {
      setError(errorText(err, "NOVA could not remove that notification destination."))
    } finally {
      setWorking(false)
    }
  }

  const makeDefaultDestination = async (id: number) => {
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

  const changePermission = async (
    permission: Permission,
    mode: Permission["mode"],
  ) => {
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
    if (
      working ||
      !window.confirm(
        `Remove ${permission.tool}/${permission.action} permission?`,
      )
    ) {
      return
    }

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

  const resolveConfirmation = async (
    id: number,
    action: "approve" | "reject",
  ) => {
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
    <div className="content-shell resource-shell settings-shell control-center-shell">
      <section className="resource-hero">
        <div>
          <div className="section-kicker">CONTROL CENTER</div>
          <h1>Keep NOVA under your control.</h1>
          <p>
            Configure proactive delivery, review sensitive actions, define
            permission rules, and monitor durable execution from one place.
          </p>
        </div>

        <div className="settings-counter">
          <span>Needs attention</span>
          <strong>{confirmations.length + activeWorkflows.length}</strong>
        </div>
      </section>

      <div
        className="settings-tabs"
        role="tablist"
        aria-label="NOVA control center"
      >
        {(
          [
            ["notifications", "Notifications"],
            ["approvals", "Approvals"],
            ["permissions", "Permissions"],
            ["workflows", "Workflows"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            className={
              tab === value ? "settings-tab active" : "settings-tab"
            }
            type="button"
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="resource-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <div className="resource-loading">Loading control center…</div>
      ) : (
        <>
          {tab === "notifications" && preferences && (
            <section className="resource-two-column">
              <article className="resource-panel">
                <div className="resource-panel-head">
                  <div>
                    <div className="section-kicker">DELIVERY</div>
                    <h2>How NOVA reaches you.</h2>
                  </div>
                </div>

                <div className="field-grid">
                  <label className="field field-span-2">
                    <span>Timezone</span>
                    <input
                      value={preferences.timezone}
                      onChange={(event) =>
                        setPreferences({
                          ...preferences,
                          timezone: event.target.value,
                        })
                      }
                      onBlur={() =>
                        void updatePreference({
                          timezone: preferences.timezone,
                        })
                      }
                    />
                  </label>

                  <label className="toggle-field field-span-2">
                    <input
                      type="checkbox"
                      checked={preferences.daily_activity_digest_enabled}
                      onChange={(event) =>
                        void updatePreference({
                          daily_activity_digest_enabled: event.target.checked,
                        })
                      }
                    />
                    <span>
                      <strong>Daily activity digest</strong>
                      <small>
                        Allow NOVA to deliver the configured proactive summary.
                      </small>
                    </span>
                  </label>

                  <label className="field">
                    <span>Delivery hour</span>
                    <input
                      type="number"
                      min={0}
                      max={23}
                      value={preferences.delivery_hour}
                      onChange={(event) =>
                        setPreferences({
                          ...preferences,
                          delivery_hour: Number(event.target.value),
                        })
                      }
                      onBlur={() =>
                        void updatePreference({
                          delivery_hour: preferences.delivery_hour,
                        })
                      }
                    />
                  </label>

                  <label className="field">
                    <span>Delivery minute</span>
                    <input
                      type="number"
                      min={0}
                      max={59}
                      value={preferences.delivery_minute}
                      onChange={(event) =>
                        setPreferences({
                          ...preferences,
                          delivery_minute: Number(event.target.value),
                        })
                      }
                      onBlur={() =>
                        void updatePreference({
                          delivery_minute: preferences.delivery_minute,
                        })
                      }
                    />
                  </label>
                </div>

                <p className="resource-hint">
                  Changes save directly through NOVA’s authenticated
                  notification-preferences API.
                </p>
              </article>

              <NotificationDestinations
                destinations={destinations}
                working={working}
                onAdd={addDestination}
                onDefault={makeDefaultDestination}
                onDelete={removeDestination}
              />
            </section>
          )}

          {tab === "approvals" && (
            <section className="settings-stack">
              <article className="resource-panel">
                <div className="resource-panel-head">
                  <div>
                    <div className="section-kicker">APPROVAL QUEUE</div>
                    <h2>Actions waiting for you.</h2>
                  </div>
                  <span className="status-pill">
                    {confirmations.length} pending
                  </span>
                </div>

                {confirmations.length === 0 ? (
                  <div className="resource-empty inline-empty">
                    <Icon name="check" size={20} />
                    <span>No pending approvals.</span>
                  </div>
                ) : (
                  <div className="confirmation-list">
                    {confirmations.map((item) => (
                      <article className="confirmation-card" key={item.id}>
                        <div className="timeline-head">
                          <div>
                            <div className="resource-card-kicker">
                              {item.tool} · {item.action}
                            </div>
                            <h3>Approval #{item.id}</h3>
                          </div>
                          <span className="status-pill status-pending">
                            {item.status}
                          </span>
                        </div>

                        <p>{item.reason}</p>
                        <pre className="code-block">
                          {JSON.stringify(item.data, null, 2)}
                        </pre>
                        <small>Expires {formatDate(item.expires_at)}</small>

                        <div className="resource-actions">
                          <button
                            className="primary-action compact"
                            type="button"
                            disabled={working}
                            onClick={() =>
                              void resolveConfirmation(item.id, "approve")
                            }
                          >
                            Approve & execute
                          </button>
                          <button
                            className="danger-action compact"
                            type="button"
                            disabled={working}
                            onClick={() =>
                              void resolveConfirmation(item.id, "reject")
                            }
                          >
                            Reject
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </article>
            </section>
          )}

          {tab === "permissions" && (
            <section className="resource-panel">
              <div className="resource-panel-head">
                <div>
                  <div className="section-kicker">PERMISSIONS</div>
                  <h2>Saved action rules.</h2>
                </div>
                <span className="status-pill">
                  {permissions.length} saved
                </span>
              </div>

              <PermissionEditor
                permissions={permissions}
                working={working}
                onChange={changePermission}
                onDelete={removePermission}
              />
            </section>
          )}

          {tab === "workflows" && (
            <section className="resource-panel">
              <div className="resource-panel-head">
                <div>
                  <div className="section-kicker">DURABLE EXECUTION</div>
                  <h2>Workflows and their steps.</h2>
                </div>
                <span className="status-pill">
                  {activeWorkflows.length} active
                </span>
              </div>

              {workflows.length === 0 ? (
                <div className="resource-empty inline-empty">
                  <Icon name="activity" size={20} />
                  <span>No workflows have been recorded yet.</span>
                </div>
              ) : (
                <div className="workflow-list">
                  {workflows.map((workflow) => (
                    <article className="workflow-card" key={workflow.id}>
                      <div className="timeline-head">
                        <div>
                          <div className="resource-card-kicker">
                            WORKFLOW #{workflow.id} · {workflow.execution_mode}
                          </div>
                          <h3>
                            {workflow.plan?.title
                              ? String(workflow.plan.title)
                              : `Workflow #${workflow.id}`}
                          </h3>
                        </div>
                        <span
                          className={`status-pill status-${workflow.status}`}
                        >
                          {workflow.status}
                        </span>
                      </div>

                      <p>
                        {workflow.error ||
                          (workflow.result
                            ? "Execution produced a result."
                            : "Durable execution is tracked step-by-step by NOVA.")}
                      </p>

                      <div className="workflow-meta">
                        <span>
                          Steps <strong>{workflow.steps.length}</strong>
                        </span>
                        <span>
                          Created <strong>{formatDate(workflow.created_at)}</strong>
                        </span>
                        <span>
                          Scheduled{" "}
                          <strong>{formatDate(workflow.scheduled_at)}</strong>
                        </span>
                      </div>

                      <div className="workflow-steps">
                        {workflow.steps.map((step) => (
                          <div className="workflow-step" key={step.id}>
                            <span>{step.position + 1}</span>
                            <div>
                              <strong>
                                {step.tool} / {step.action}
                              </strong>
                              <small>
                                {step.status} · attempts {step.attempts}
                              </small>
                            </div>
                          </div>
                        ))}
                      </div>

                      {!["completed", "cancelled", "failed"].includes(
                        workflow.status,
                      ) && (
                        <div className="resource-actions">
                          <button
                            className="danger-action compact"
                            type="button"
                            disabled={working}
                            onClick={() => void stopWorkflow(workflow.id)}
                          >
                            Cancel workflow
                          </button>
                        </div>
                      )}
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
  onAdd: (
    channel: string,
    destination: string,
    label: string,
    isDefault: boolean,
  ) => Promise<void>
  onDefault: (id: number) => Promise<void>
  onDelete: (id: number) => Promise<void>
}) {
  const [form, setForm] = useState({
    channel: "email",
    destination: "",
    label: "",
    isDefault: false,
  })

  const submit = async () => {
    if (!form.destination.trim() || working) return

    await onAdd(
      form.channel,
      form.destination,
      form.label,
      form.isDefault,
    )

    setForm({
      channel: "email",
      destination: "",
      label: "",
      isDefault: false,
    })
  }

  return (
    <article className="resource-panel">
      <div className="resource-panel-head">
        <div>
          <div className="section-kicker">DESTINATIONS</div>
          <h2>Where NOVA can notify you.</h2>
        </div>
      </div>

      {destinations.length === 0 ? (
        <div className="resource-empty inline-empty">
          <span>No notification destinations configured.</span>
        </div>
      ) : (
        <div className="destination-list">
          {destinations.map((destination) => (
            <div className="destination-row" key={destination.id}>
              <div>
                <span className="resource-card-kicker">
                  {destination.channel}
                </span>
                <strong>
                  {destination.label || destination.destination}
                </strong>
                <small>{destination.destination}</small>
              </div>

              <div className="resource-actions">
                {destination.is_default ? (
                  <span className="status-pill status-completed">Default</span>
                ) : (
                  <button
                    className="secondary-action compact"
                    type="button"
                    disabled={working}
                    onClick={() => void onDefault(destination.id)}
                  >
                    Make default
                  </button>
                )}
                <button
                  className="icon-action danger"
                  type="button"
                  disabled={working}
                  onClick={() => void onDelete(destination.id)}
                  aria-label="Remove notification destination"
                >
                  <Icon name="trash" size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="settings-divider" />

      <div className="field-grid">
        <label className="field">
          <span>Channel</span>
          <select
            value={form.channel}
            onChange={(event) =>
              setForm({ ...form, channel: event.target.value })
            }
          >
            <option value="email">Email</option>
            <option value="web">Web</option>
            <option value="sms">SMS</option>
            <option value="push">Push</option>
            <option value="whatsapp">WhatsApp</option>
          </select>
        </label>

        <label className="field">
          <span>Destination</span>
          <input
            value={form.destination}
            onChange={(event) =>
              setForm({ ...form, destination: event.target.value })
            }
            placeholder="you@example.com"
          />
        </label>

        <label className="field">
          <span>Label</span>
          <input
            value={form.label}
            onChange={(event) =>
              setForm({ ...form, label: event.target.value })
            }
            placeholder="Primary"
          />
        </label>

        <label className="toggle-field">
          <input
            type="checkbox"
            checked={form.isDefault}
            onChange={(event) =>
              setForm({ ...form, isDefault: event.target.checked })
            }
          />
          <span>
            <strong>Set default</strong>
            <small>Use this destination for default delivery.</small>
          </span>
        </label>
      </div>

      <button
        className="secondary-action"
        type="button"
        disabled={working || !form.destination.trim()}
        onClick={() => void submit()}
      >
        <Icon name="plus" size={15} />
        Add destination
      </button>
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
  onChange: (
    permission: Permission,
    mode: Permission["mode"],
  ) => Promise<void>
  onDelete: (permission: Permission) => Promise<void>
}) {
  const [form, setForm] = useState<{
    tool: string
    action: Permission["action"]
    mode: Permission["mode"]
  }>({
    tool: "task",
    action: "create",
    mode: "confirm",
  })

  return (
    <div className="permission-area">
      <div className="permission-list">
        {permissions.length === 0 ? (
          <div className="resource-empty inline-empty">
            <span>
              No saved permissions. NOVA will use its deterministic safety
              defaults.
            </span>
          </div>
        ) : (
          permissions.map((permission) => (
            <div
              className="permission-row"
              key={`${permission.tool}-${permission.action}`}
            >
              <div>
                <strong>{permission.tool}</strong>
                <span>/ {permission.action}</span>
                <small>Updated {formatDate(permission.updated_at)}</small>
              </div>

              <div className="resource-actions">
                <select
                  value={permission.mode}
                  disabled={working}
                  onChange={(event) =>
                    void onChange(
                      permission,
                      event.target.value as Permission["mode"],
                    )
                  }
                >
                  <option value="allow">Allow</option>
                  <option value="confirm">Confirm</option>
                  <option value="deny">Deny</option>
                </select>

                <button
                  className="icon-action danger"
                  type="button"
                  disabled={working}
                  onClick={() => void onDelete(permission)}
                  aria-label={`Remove ${permission.tool} ${permission.action} permission`}
                >
                  <Icon name="trash" size={14} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="settings-divider" />

      <div className="resource-card-kicker">ADD / OVERRIDE RULE</div>

      <div className="field-grid">
        <label className="field">
          <span>Tool</span>
          <input
            value={form.tool}
            onChange={(event) =>
              setForm({ ...form, tool: event.target.value })
            }
            placeholder="task"
          />
        </label>

        <label className="field">
          <span>Action</span>
          <select
            value={form.action}
            onChange={(event) =>
              setForm({
                ...form,
                action: event.target.value as Permission["action"],
              })
            }
          >
            {permissionActions.map((action) => (
              <option key={action} value={action}>
                {action}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Mode</span>
          <select
            value={form.mode}
            onChange={(event) =>
              setForm({
                ...form,
                mode: event.target.value as Permission["mode"],
              })
            }
          >
            <option value="allow">Allow</option>
            <option value="confirm">Confirm</option>
            <option value="deny">Deny</option>
          </select>
        </label>

        <div className="form-actions">
          <button
            className="secondary-action compact"
            type="button"
            disabled={working || !form.tool.trim()}
            onClick={() =>
              void onChange(
                {
                  id: 0,
                  tool: form.tool.trim(),
                  action: form.action,
                  mode: form.mode,
                  created_at: "",
                  updated_at: "",
                },
                form.mode,
              )
            }
          >
            Save rule
          </button>
        </div>
      </div>
    </div>
  )
}
