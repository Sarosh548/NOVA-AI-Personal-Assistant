import { useEffect, useRef, useState } from "react"

import { Icon } from "../components/Icon"
import "./AccountMenu.css"

type AccountMenuProps = {
  displayName: string
  onSignOut: () => Promise<void>
}

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

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
  const [isSigningOut, setIsSigningOut] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const profileButtonRef = useRef<HTMLButtonElement | null>(null)
  const signOutButtonRef = useRef<HTMLButtonElement | null>(null)
  const wasOpenRef = useRef(false)

  useEffect(() => {
    if (!open) {
      if (wasOpenRef.current) {
        profileButtonRef.current?.focus()
      }
      wasOpenRef.current = false
      return
    }

    wasOpenRef.current = true

    const frame = window.requestAnimationFrame(() => {
      signOutButtonRef.current?.focus()
    })

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target
      if (target instanceof Node && !containerRef.current?.contains(target)) {
        setOpen(false)
      }
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault()
        setOpen(false)
        return
      }

      if (event.key !== "Tab") return

      const menu = containerRef.current
      if (!menu) return

      const focusable = Array.from(
        menu.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      )

      if (focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener("pointerdown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)

    return () => {
      window.cancelAnimationFrame(frame)
      document.removeEventListener("pointerdown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [open])

  const handleSignOut = async () => {
    if (isSigningOut) return

    setIsSigningOut(true)
    try {
      await onSignOut()
    } catch (error) {
      console.error("NOVA sign out failed", error)
    } finally {
      setIsSigningOut(false)
      setOpen(false)
    }
  }

  const initials = initialsFor(displayName)

  return (
    <div className="account-menu" ref={containerRef}>
      <button
        ref={profileButtonRef}
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
            ref={signOutButtonRef}
            className="account-menu-item danger"
            type="button"
            role="menuitem"
            disabled={isSigningOut}
            aria-busy={isSigningOut}
            onClick={() => void handleSignOut()}
          >
            <Icon name="logout" size={16} />
            <span>{isSigningOut ? "Signing out…" : "Sign out"}</span>
          </button>
        </div>
      ) : null}
    </div>
  )
}
