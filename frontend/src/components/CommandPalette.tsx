import { useEffect, useMemo, useRef, useState } from "react"

import { Icon } from "./Icon"
import { navigation, type SurfaceKey } from "../app/navigation"

type CommandPaletteProps = {
  open: boolean
  activeSurface: SurfaceKey
  onClose: () => void
  onNavigate: (surface: SurfaceKey) => void
}

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function commandId(label: SurfaceKey): string {
  return `nova-command-${label.toLowerCase().replace(/\s+/g, "-")}`
}

export function CommandPalette({
  open,
  activeSurface,
  onClose,
  onNavigate,
}: CommandPaletteProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const paletteRef = useRef<HTMLDivElement | null>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)
  const [query, setQuery] = useState("")
  const [selectedIndex, setSelectedIndex] = useState(0)

  const filteredNavigation = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return navigation
    return navigation.filter((item) =>
      item.label.toLowerCase().includes(normalized),
    )
  }, [query])

  const selectedItem = filteredNavigation[selectedIndex]
  const selectedItemId = selectedItem ? commandId(selectedItem.label) : undefined

  useEffect(() => {
    if (!open) return

    previousFocusRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    setQuery("")
    setSelectedIndex(0)

    const frame = window.requestAnimationFrame(() => {
      inputRef.current?.focus()
    })

    return () => {
      window.cancelAnimationFrame(frame)
    }
  }, [open])

  useEffect(() => {
    if (!open) return

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault()
        onClose()
        return
      }

      if (event.key === "Tab") {
        const palette = paletteRef.current
        if (!palette) return

        const focusable = Array.from(
          palette.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
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
        return
      }

      if (event.key === "ArrowDown") {
        event.preventDefault()
        setSelectedIndex((current) =>
          filteredNavigation.length === 0
            ? 0
            : (current + 1) % filteredNavigation.length,
        )
        return
      }

      if (event.key === "ArrowUp") {
        event.preventDefault()
        setSelectedIndex((current) =>
          filteredNavigation.length === 0
            ? 0
            : (current - 1 + filteredNavigation.length) %
              filteredNavigation.length,
        )
        return
      }

      if (event.key === "Enter") {
        event.preventDefault()
        const selected = filteredNavigation[selectedIndex]
        if (!selected) return
        onNavigate(selected.label)
        onClose()
      }
    }

    document.addEventListener("keydown", handleKeyDown)
    return () => document.removeEventListener("keydown", handleKeyDown)
  }, [
    filteredNavigation,
    onClose,
    onNavigate,
    open,
    selectedIndex,
  ])

  useEffect(() => {
    if (open) return
    previousFocusRef.current?.focus()
    previousFocusRef.current = null
  }, [open])

  if (!open) return null

  return (
    <div className="command-palette-layer">
      <button
        className="command-palette-backdrop"
        type="button"
        aria-label="Close command palette"
        onClick={onClose}
      />

      <div
        ref={paletteRef}
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="NOVA command palette"
      >
        <div className="command-palette-search">
          <Icon name="search" size={17} />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setSelectedIndex(0)
            }}
            placeholder="Jump to a NOVA workspace…"
            aria-label="Search NOVA workspaces"
            role="combobox"
            aria-expanded="true"
            aria-autocomplete="list"
            aria-controls="nova-command-list"
            aria-activedescendant={selectedItemId}
          />
          <kbd>Esc</kbd>
        </div>

        <div
          id="nova-command-list"
          className="command-palette-list"
          role="listbox"
          aria-label="NOVA workspaces"
        >
          {filteredNavigation.length === 0 ? (
            <div className="command-palette-empty">No matching workspace.</div>
          ) : (
            filteredNavigation.map((item, index) => {
              const selected = index === selectedIndex

              return (
                <button
                  id={commandId(item.label)}
                  className={
                    selected
                      ? "command-palette-item selected"
                      : "command-palette-item"
                  }
                  key={item.label}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onMouseEnter={() => setSelectedIndex(index)}
                  onClick={() => {
                    onNavigate(item.label)
                    onClose()
                  }}
                >
                  <span className="command-palette-item-icon">
                    <Icon name={item.icon} size={17} />
                  </span>
                  <span>
                    <strong>{item.label}</strong>
                    <small>
                      {item.label === activeSurface
                        ? "Current workspace"
                        : item.group === "workspace"
                          ? "Workspace"
                          : "Personal"}
                    </small>
                  </span>
                  {selected && <span className="command-palette-enter">↵</span>}
                </button>
              )
            })
          )}
        </div>

        <div className="command-palette-footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
          <span><kbd>Enter</kbd> open</span>
          <span><kbd>Esc</kbd> close</span>
        </div>
      </div>
    </div>
  )
}
