import { useEffect, useRef, useState } from "react"

import { Icon } from "../components/Icon"
import "./AccountMenu.css"

type AccountMenuProps = {
  displayName: string
  onSignOut: () => Promise<void>
}

function initialsFor(name: string): string {
  const initials = name
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("")

  return initials || "SQ"
}

export function AccountMenu({
  displayName,
  onSignOut,
}: AccountMenuProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) {
      return
    }

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target
      if (target instanceof Node && !containerRef.current?.contains(target)) {
        setOpen(false)
      }
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false)
      }
    }

    document.addEventListener("pointerdown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [open])

  const handleSignOut = async () => {
    setOpen(false)
    await onSignOut()
  }

  const initials = initialsFor(displayName)

  return (
    <div className="account-menu" ref={containerRef}>
      <button
        className="profile-button"
        type="button"
        aria-label="Open account menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="avatar">{initials}</span>
        <span className="profile-name">Account</span>
      </button>

      {open ? (
        <div className="account-menu-popover" role="menu" aria-label="Account menu">
          <div className="account-menu-summary">
            <span className="account-menu-kicker">Signed in</span>
            <span className="account-menu-name">{displayName}</span>
          </div>

          <div className="account-menu-divider" />

          <button
            className="account-menu-item danger"
            type="button"
            role="menuitem"
            onClick={() => void handleSignOut()}
          >
            <Icon name="logout" size={16} />
            <span>Sign out</span>
          </button>
        </div>
      ) : null}
    </div>
  )
}
