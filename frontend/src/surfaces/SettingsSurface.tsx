import { useAuth } from "../auth/AuthProvider"
import { Icon } from "../components/Icon"

function formatDate(value: string | null): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

export function SettingsSurface() {
  const { user } = useAuth()

  return (
    <div className="content-shell resource-shell settings-shell">
      <section className="resource-hero">
        <div>
          <div className="section-kicker">SETTINGS</div>
          <h1>Your account and NOVA foundation.</h1>
          <p>
            Review your authenticated identity and the capabilities currently
            available in this frontend workspace.
          </p>
        </div>

        <div className="settings-counter">
          <span>Session</span>
          <strong>{user?.is_active ? "Active" : "—"}</strong>
        </div>
      </section>

      <section className="resource-two-column">
        <article className="resource-panel">
          <div className="resource-panel-head">
            <div>
              <div className="section-kicker">ACCOUNT</div>
              <h2>Your NOVA identity.</h2>
            </div>
          </div>

          <div className="settings-profile">
            <div className="settings-avatar">
              {(user?.display_name?.[0] || "N").toUpperCase()}
            </div>
            <div>
              <span className="resource-card-kicker">DISPLAY NAME</span>
              <strong>{user?.display_name || "NOVA user"}</strong>
              <small>{user?.id}</small>
            </div>
          </div>

          <div className="settings-detail-grid">
            <div>
              <span>Status</span>
              <strong>{user?.is_active ? "Active" : "Inactive"}</strong>
            </div>
            <div>
              <span>Created</span>
              <strong>{formatDate(user?.created_at ?? null)}</strong>
            </div>
            <div>
              <span>Updated</span>
              <strong>{formatDate(user?.updated_at ?? null)}</strong>
            </div>
          </div>
        </article>

        <article className="resource-panel">
          <div className="resource-panel-head">
            <div>
              <div className="section-kicker">SYSTEM</div>
              <h2>Frontend foundation.</h2>
            </div>
          </div>

          <div className="settings-check-list">
            <div>
              <Icon name="check" size={16} />
              <span>Authenticated account session</span>
              <strong>Ready</strong>
            </div>
            <div>
              <Icon name="check" size={16} />
              <span>Conversation workspace</span>
              <strong>Ready</strong>
            </div>
            <div>
              <Icon name="check" size={16} />
              <span>Realtime voice workspace</span>
              <strong>Ready</strong>
            </div>
            <div>
              <Icon name="check" size={16} />
              <span>Task, reminder & calendar controls</span>
              <strong>Ready</strong>
            </div>
            <div>
              <Icon name="check" size={16} />
              <span>Memory & private knowledge</span>
              <strong>Ready</strong>
            </div>
            <div>
              <Icon name="check" size={16} />
              <span>Control center for proactive and sensitive actions</span>
              <strong>Ready</strong>
            </div>
          </div>
        </article>
      </section>
    </div>
  )
}
