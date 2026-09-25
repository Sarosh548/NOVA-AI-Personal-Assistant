import { useEffect, useState, type ReactNode } from "react"

import { navigation, type SurfaceKey } from "../app/navigation"
import { AccountMenu } from "../components/AccountMenu"
import { CommandPalette } from "../components/CommandPalette"
import { Icon } from "../components/Icon"

type AppShellProps = {
  activeSurface: SurfaceKey
  onNavigate: (surface: SurfaceKey) => void
  displayName: string
  onSignOut: () => Promise<void>
  children: ReactNode
}

export function AppShell({
  activeSurface,
  onNavigate,
  displayName,
  onSignOut,
  children,
}: AppShellProps) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false)
  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine,
  )

  const activeLabel =
    navigation.find((item) => item.label === activeSurface)?.label ?? "Home"

  const workspace = navigation.filter((item) => item.group === "workspace")
  const system = navigation.filter((item) => item.group === "system")

  useEffect(() => {
    if (!mobileMenuOpen) return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileMenuOpen(false)
      }
    }

    document.addEventListener("keydown", handleKeyDown)
    document.body.style.overflow = "hidden"

    return () => {
      document.removeEventListener("keydown", handleKeyDown)
      document.body.style.overflow = ""
    }
  }, [mobileMenuOpen])

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === "k"
      ) {
        event.preventDefault()
        setCommandPaletteOpen(true)
      }
    }

    document.addEventListener("keydown", handleShortcut)
    return () => document.removeEventListener("keydown", handleShortcut)
  }, [])

  useEffect(() => {
    const updateOnlineState = () => setOnline(navigator.onLine)

    window.addEventListener("online", updateOnlineState)
    window.addEventListener("offline", updateOnlineState)

    return () => {
      window.removeEventListener("online", updateOnlineState)
      window.removeEventListener("offline", updateOnlineState)
    }
  }, [])

  const navigateFromMobile = (surface: SurfaceKey) => {
    onNavigate(surface)
    setMobileMenuOpen(false)
  }

  const renderNavigationItem = (
    item: (typeof navigation)[number],
    mobile = false,
  ) => (
    <button
      className={item.label === activeSurface ? "nav-item active" : "nav-item"}
      key={item.label}
      type="button"
      onClick={() => (mobile ? navigateFromMobile(item.label) : onNavigate(item.label))}
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
            {workspace.map((item) => renderNavigationItem(item))}
          </div>

          <div className="nav-group">
            <div className="nav-label">Personal</div>
            {system.map((item) => renderNavigationItem(item))}
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
          <div className="mobile-topbar-left">
            <button
              className="mobile-menu-button"
              type="button"
              aria-label="Open navigation"
              aria-expanded={mobileMenuOpen}
              aria-controls="mobile-navigation"
              onClick={() => setMobileMenuOpen(true)}
            >
              <Icon name="menu" size={19} />
            </button>

            <div className="mobile-brand">
              <div className="brand-mark">
                <Icon name="spark" size={17} />
              </div>
              <span className="brand-name">NOVA</span>
            </div>
          </div>

          <div className="breadcrumb" aria-label="Current location">
            <span className="muted">NOVA</span>
            <span className="separator">/</span>
            <span>{activeLabel}</span>
          </div>

          <div className="topbar-actions">
            {!online && (
              <div className="network-status offline" role="status">
                <span className="connection-dot" />
                Offline
              </div>
            )}
            <button
              className="command-trigger"
              type="button"
              onClick={() => setCommandPaletteOpen(true)}
              aria-label="Open command palette"
              title="Open command palette"
            >
              <Icon name="search" size={16} />
              <span>Jump to…</span>
              <kbd>Ctrl K</kbd>
            </button>
            <AccountMenu
              displayName={displayName}
              onSignOut={onSignOut}
            />
          </div>
        </header>

        {children}
      </main>

      {!online && (
        <div className="network-banner" role="status" aria-live="polite">
          You’re offline. NOVA will reconnect to online services when your connection returns.
        </div>
      )}

      {mobileMenuOpen && (
        <div className="mobile-navigation-layer">
          <button
            className="mobile-navigation-backdrop"
            type="button"
            aria-label="Close navigation"
            onClick={() => setMobileMenuOpen(false)}
          />

          <aside
            id="mobile-navigation"
            className="mobile-navigation-drawer"
            aria-label="Mobile navigation"
          >
            <div className="mobile-navigation-header">
              <div className="brand">
                <div className="brand-mark">
                  <Icon name="spark" size={18} />
                </div>
                <div>
                  <div className="brand-name">NOVA</div>
                  <div className="brand-caption">Personal AI</div>
                </div>
              </div>

              <button
                className="icon-action"
                type="button"
                aria-label="Close navigation"
                onClick={() => setMobileMenuOpen(false)}
              >
                <Icon name="close" size={18} />
              </button>
            </div>

            <nav className="mobile-navigation-content" aria-label="Mobile primary navigation">
              <div className="nav-group">
                <div className="nav-label">Workspace</div>
                {workspace.map((item) => renderNavigationItem(item, true))}
              </div>

              <div className="nav-group">
                <div className="nav-label">Personal</div>
                {system.map((item) => renderNavigationItem(item, true))}
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
        </div>
      )}

      <CommandPalette
        open={commandPaletteOpen}
        activeSurface={activeSurface}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={onNavigate}
      />
    </div>
  )
}
