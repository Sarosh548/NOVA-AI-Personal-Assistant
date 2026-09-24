import { useMemo, useState } from "react"

type SurfaceKey =
  | "Home"
  | "Conversation"
  | "Tasks"
  | "Reminders"
  | "Calendar"
  | "Activity"
  | "Memory"
  | "Knowledge"
  | "Settings"

type IconName =
  | "spark"
  | "home"
  | "message"
  | "check"
  | "bell"
  | "calendar"
  | "activity"
  | "brain"
  | "book"
  | "settings"
  | "plus"
  | "arrow"
  | "mic"

type IconProps = {
  name: IconName
  size?: number
}

const navigation: Array<{
  label: SurfaceKey
  icon: IconName
  group: "workspace" | "system"
}> = [
  { label: "Home", icon: "home", group: "workspace" },
  { label: "Conversation", icon: "message", group: "workspace" },
  { label: "Tasks", icon: "check", group: "workspace" },
  { label: "Reminders", icon: "bell", group: "workspace" },
  { label: "Calendar", icon: "calendar", group: "workspace" },
  { label: "Activity", icon: "activity", group: "workspace" },
  { label: "Memory", icon: "brain", group: "system" },
  { label: "Knowledge", icon: "book", group: "system" },
  { label: "Settings", icon: "settings", group: "system" },
]

function Icon({ name, size = 20 }: IconProps) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  }

  switch (name) {
    case "spark":
      return (
        <svg {...common}>
          <path d="M12 3l1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3z" />
          <path d="M19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16z" />
        </svg>
      )
    case "home":
      return (
        <svg {...common}>
          <path d="M3.5 10.7L12 3.8l8.5 6.9" />
          <path d="M5.5 9.5v10.7h13V9.5" />
          <path d="M9.5 20.2v-6h5v6" />
        </svg>
      )
    case "message":
      return (
        <svg {...common}>
          <path d="M5 5.5h14v9H9l-4 3v-12z" />
          <path d="M8 9h8M8 12h5" />
        </svg>
      )
    case "check":
      return (
        <svg {...common}>
          <rect x="4" y="4" width="16" height="16" rx="4" />
          <path d="M8 12.2l2.5 2.5 5.5-5.7" />
        </svg>
      )
    case "bell":
      return (
        <svg {...common}>
          <path d="M6.5 10a5.5 5.5 0 0111 0v3.2l1.5 2.3H5l1.5-2.3V10z" />
          <path d="M10 18h4" />
        </svg>
      )
    case "calendar":
      return (
        <svg {...common}>
          <rect x="4" y="5.5" width="16" height="14" rx="3" />
          <path d="M8 3.5v4M16 3.5v4M4 10h16M8 13h3M13 13h3M8 16h3" />
        </svg>
      )
    case "activity":
      return (
        <svg {...common}>
          <path d="M4 14h3l2-7 4 12 2.2-7H20" />
        </svg>
      )
    case "brain":
      return (
        <svg {...common}>
          <path d="M9 5.2A3.2 3.2 0 006 8.4v.2A3.5 3.5 0 006.5 15 3.2 3.2 0 009 18.1V5.2z" />
          <path d="M15 5.2a3.2 3.2 0 013 3.2v.2a3.5 3.5 0 01-.5 6.4 3.2 3.2 0 01-2.5 3.1V5.2z" />
          <path d="M9 9h2M13 9h2M9 13h2M13 13h2M12 5v14" />
        </svg>
      )
    case "book":
      return (
        <svg {...common}>
          <path d="M4 5.5a2 2 0 012-2h5v16H6a2 2 0 01-2-2v-12z" />
          <path d="M20 5.5a2 2 0 00-2-2h-5v16h5a2 2 0 002-2v-12z" />
        </svg>
      )
    case "settings":
      return (
        <svg {...common}>
          <path d="M12 8.5a3.5 3.5 0 100 7 3.5 3.5 0 000-7z" />
          <path d="M19 13.2v-2.4l-2-.6a6.4 6.4 0 00-.8-1.8l1-1.8-1.7-1.7-1.8 1a6.4 6.4 0 00-1.8-.8l-.6-2h-2.4l-.6 2a6.4 6.4 0 00-1.8.8l-1.8-1L4.1 6.6l1 1.8a6.4 6.4 0 00-.8 1.8l-2 .6v2.4l2 .6c.2.7.4 1.2.8 1.8l-1 1.8 1.7 1.7 1.8-1c.6.4 1.2.7 1.8.8l.6 2h2.4l.6-2a6.4 6.4 0 001.8-.8l1.8 1 1.7-1.7-1-1.8c.4-.6.7-1.2.8-1.8l2-.6z" />
        </svg>
      )
    case "plus":
      return (
        <svg {...common}>
          <path d="M12 5v14M5 12h14" />
        </svg>
      )
    case "arrow":
      return (
        <svg {...common}>
          <path d="M5 12h13M13 6l6 6-6 6" />
        </svg>
      )
    case "mic":
      return (
        <svg {...common}>
          <rect x="8.5" y="3.5" width="7" height="11" rx="3.5" />
          <path d="M6 11.5a6 6 0 0012 0M12 17.5v3M9 20.5h6" />
        </svg>
      )
  }
}

function App() {
  const [activeSurface, setActiveSurface] = useState<SurfaceKey>("Home")

  const activeLabel = useMemo(
    () => navigation.find((item) => item.label === activeSurface)?.label ?? "Home",
    [activeSurface],
  )

  const groupedNavigation = {
    workspace: navigation.filter((item) => item.group === "workspace"),
    system: navigation.filter((item) => item.group === "system"),
  }

  return (
    <div className="nova-app">
      <aside className="nova-sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Icon name="spark" size={18} />
          </div>
          <div>
            <div className="brand-name">NOVA</div>
            <div className="brand-caption">Personal AI</div>
          </div>
        </div>

        <nav className="nav-stack" aria-label="Primary navigation">
          <div className="nav-group">
            <div className="nav-label">Workspace</div>
            {groupedNavigation.workspace.map((item) => (
              <button
                className={item.label === activeSurface ? "nav-item active" : "nav-item"}
                key={item.label}
                type="button"
                onClick={() => setActiveSurface(item.label)}
                aria-current={item.label === activeSurface ? "page" : undefined}
              >
                <Icon name={item.icon} size={19} />
                <span>{item.label}</span>
              </button>
            ))}
          </div>

          <div className="nav-group">
            <div className="nav-label">Personal</div>
            {groupedNavigation.system.map((item) => (
              <button
                className={item.label === activeSurface ? "nav-item active" : "nav-item"}
                key={item.label}
                type="button"
                onClick={() => setActiveSurface(item.label)}
                aria-current={item.label === activeSurface ? "page" : undefined}
              >
                <Icon name={item.icon} size={19} />
                <span>{item.label}</span>
              </button>
            ))}
          </div>
        </nav>

        <div className="sidebar-footer">
          <div className="connection-dot" />
          <div>
            <div className="footer-title">Foundation mode</div>
            <div className="footer-copy">Core client shell ready</div>
          </div>
        </div>
      </aside>

      <main className="nova-main">
        <header className="topbar">
          <div className="mobile-brand">
            <div className="brand-mark">
              <Icon name="spark" size={17} />
            </div>
            <span className="brand-name">NOVA</span>
          </div>

          <div className="breadcrumb">
            <span className="muted">NOVA</span>
            <span className="separator">/</span>
            <span>{activeLabel}</span>
          </div>

          <div className="topbar-actions">
            <button className="profile-button" type="button" aria-label="Account">
              <span className="avatar">SQ</span>
              <span className="profile-name">Account</span>
            </button>
          </div>
        </header>

        {activeSurface === "Home" ? (
          <HomeSurface onOpenConversation={() => setActiveSurface("Conversation")} />
        ) : (
          <PlaceholderSurface
            label={activeSurface}
            onBackHome={() => setActiveSurface("Home")}
          />
        )}
      </main>
    </div>
  )
}

function HomeSurface({
  onOpenConversation,
}: {
  onOpenConversation: () => void
}) {
  return (
    <div className="content-shell">
      <section className="hero-grid">
        <div>
          <div className="eyebrow">
            <span className="eyebrow-dot" />
            PERSONAL COMMAND CENTER
          </div>
          <h1>Your day, with less friction.</h1>
          <p className="hero-copy">
            NOVA is being shaped as a voice-first executive assistant:
            conversation, planning, memory, research, and authorized action in one place.
          </p>

          <div className="hero-actions">
            <button className="primary-action" type="button" onClick={onOpenConversation}>
              <Icon name="mic" size={18} />
              Start with NOVA
            </button>
            <button className="secondary-action" type="button" onClick={onOpenConversation}>
              Explore conversation
              <Icon name="arrow" size={17} />
            </button>
          </div>
        </div>

        <div className="orb-card" aria-label="NOVA assistant status">
          <div className="orb-glow orb-glow-one" />
          <div className="orb-glow orb-glow-two" />
          <div className="nova-orb">
            <div className="orb-core">
              <Icon name="spark" size={34} />
            </div>
          </div>
          <div className="orb-status">
            <span className="status-pill">Ready</span>
            <span className="orb-caption">Conversation surface next</span>
          </div>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div>
            <div className="section-kicker">QUICK ACTIONS</div>
            <h2>Move from intent to action.</h2>
          </div>
          <span className="section-note">Foundation UI</span>
        </div>

        <div className="action-grid">
          <ActionCard
            icon="message"
            title="Talk to NOVA"
            description="Open the conversation workspace."
            onClick={onOpenConversation}
          />
          <ActionCard
            icon="check"
            title="Create a task"
            description="Capture something you want NOVA to handle."
          />
          <ActionCard
            icon="bell"
            title="Set a reminder"
            description="Keep future follow-ups in one place."
          />
          <ActionCard
            icon="calendar"
            title="Plan the day"
            description="Bring schedule, priorities, and timing together."
          />
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div>
            <div className="section-kicker">TODAY</div>
            <h2>Personal context will live here.</h2>
          </div>
        </div>

        <div className="context-panel">
          <div className="context-icon">
            <Icon name="spark" size={19} />
          </div>
          <div>
            <div className="context-title">Your live dashboard is intentionally empty for now.</div>
            <p className="context-copy">
              This foundation keeps the client shell separate from backend business logic.
              The next milestones will connect authentication, conversations, tasks,
              reminders, calendar, memory, and realtime voice to their existing APIs.
            </p>
          </div>
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
  icon: IconName
  title: string
  description: string
  onClick?: () => void
}) {
  return (
    <button className="action-card" type="button" onClick={onClick}>
      <div className="action-card-icon">
        <Icon name={icon} size={19} />
      </div>
      <div className="action-card-content">
        <div className="action-card-title">{title}</div>
        <div className="action-card-copy">{description}</div>
      </div>
      <Icon name="arrow" size={17} />
    </button>
  )
}

function PlaceholderSurface({
  label,
  onBackHome,
}: {
  label: SurfaceKey
  onBackHome: () => void
}) {
  return (
    <div className="placeholder-shell">
      <div className="placeholder-card">
        <div className="placeholder-icon">
          <Icon name="spark" size={22} />
        </div>
        <div className="section-kicker">SURFACE SCAFFOLD</div>
        <h1>{label}</h1>
        <p>
          This surface is part of the NOVA product shell.
          Its real backend-connected workflow will be implemented as a separate milestone.
        </p>
        <button className="secondary-action" type="button" onClick={onBackHome}>
          Back to Home
          <Icon name="arrow" size={17} />
        </button>
      </div>
    </div>
  )
}

export default App
