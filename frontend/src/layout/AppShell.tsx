import type { ReactNode } from "react"

import { navigation, type SurfaceKey } from "../app/navigation"
import { Icon } from "../components/Icon"

type AppShellProps = {
  activeSurface: SurfaceKey
  onNavigate: (surface: SurfaceKey) => void
  children: ReactNode
}

export function AppShell({
  activeSurface,
  onNavigate,
  children,
}: AppShellProps) {
  const activeLabel =
    navigation.find((item) => item.label === activeSurface)?.label ?? "Home"

  const workspace = navigation.filter((item) => item.group === "workspace")
  const system = navigation.filter((item) => item.group === "system")

  const renderNavigationItem = (item: (typeof navigation)[number]) => (
    <button
      className={item.label === activeSurface ? "nav-item active" : "nav-item"}
      key={item.label}
      type="button"
      onClick={() => onNavigate(item.label)}
      aria-current={item.label === activeSurface ? "page" : undefined}
    >
      <Icon name={item.icon} size={19} />
      <span>{item.label}</span>
    </button>
  )

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
            {workspace.map(renderNavigationItem)}
          </div>

          <div className="nav-group">
            <div className="nav-label">Personal</div>
            {system.map(renderNavigationItem)}
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

          <div className="breadcrumb" aria-label="Current location">
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

        {children}
      </main>
    </div>
  )
}
