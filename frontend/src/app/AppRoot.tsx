import { useCallback, useEffect, useState, type ReactNode } from "react"

import { AuthScreen } from "../auth/AuthScreen"
import { AppErrorBoundary } from "../components/AppErrorBoundary"
import { useAuth } from "../auth/AuthProvider"
import { ActivitySurface } from "../surfaces/ActivitySurface"
import { CalendarSurface } from "../surfaces/CalendarSurface"
import { ControlCenterSurface } from "../surfaces/ControlCenterSurface"
import { ConversationSurface } from "../surfaces/ConversationSurface"
import { HomeSurface } from "../surfaces/HomeSurface"
import { KnowledgeSurface } from "../surfaces/KnowledgeSurface"
import { MemorySurface } from "../surfaces/MemorySurface"
import { RemindersSurface } from "../surfaces/RemindersSurface"
import { SettingsSurface } from "../surfaces/SettingsSurface"
import { TasksSurface } from "../surfaces/TasksSurface"
import { VoiceSurface } from "../surfaces/VoiceSurface"
import { AppShell } from "../layout/AppShell"
import { surfaceFromHash, surfaceHash, type SurfaceKey } from "./navigation"

export function AppRoot() {
  const { status, user, signOut } = useAuth()
  const [activeSurface, setActiveSurfaceState] = useState<SurfaceKey>(() =>
    surfaceFromHash(window.location.hash) ?? "Home",
  )

  const setActiveSurface = useCallback((surface: SurfaceKey) => {
    setActiveSurfaceState(surface)

    const nextHash = surfaceHash(surface)
    if (window.location.hash !== nextHash) {
      window.history.pushState(null, "", nextHash)
    }
  }, [])

  useEffect(() => {
    const syncSurface = () => {
      const surface = surfaceFromHash(window.location.hash)
      setActiveSurfaceState(surface ?? "Home")
    }

    window.addEventListener("hashchange", syncSurface)
    window.addEventListener("popstate", syncSurface)

    return () => {
      window.removeEventListener("hashchange", syncSurface)
      window.removeEventListener("popstate", syncSurface)
    }
  }, [])

  useEffect(() => {
    document.title =
      activeSurface === "Home" ? "NOVA — Personal AI" : `NOVA — ${activeSurface}`
  }, [activeSurface])

  if (status === "loading") {
    return (
      <div className="auth-loading" aria-live="polite">
        <div className="brand-mark"><span className="loading-pulse" /></div>
        <span>Loading NOVA…</span>
      </div>
    )
  }

  if (status === "unauthenticated") return <AuthScreen />

  const displayName = user?.display_name?.trim() || "NOVA user"

  let surface: ReactNode

  switch (activeSurface) {
    case "Home":
      surface = <HomeSurface onNavigate={setActiveSurface} />
      break
    case "Conversation":
      surface = <ConversationSurface />
      break
    case "Voice":
      surface = <VoiceSurface onOpenConversation={() => setActiveSurface("Conversation")} />
      break
    case "Tasks":
      surface = <TasksSurface />
      break
    case "Reminders":
      surface = <RemindersSurface />
      break
    case "Calendar":
      surface = <CalendarSurface />
      break
    case "Activity":
      surface = <ActivitySurface />
      break
    case "Memory":
      surface = <MemorySurface />
      break
    case "Knowledge":
      surface = <KnowledgeSurface />
      break
    case "Control Center":
      surface = <ControlCenterSurface />
      break
    case "Settings":
      surface = <SettingsSurface />
      break
    default:
      surface = <HomeSurface onNavigate={setActiveSurface} />
  }

  return (
    <AppErrorBoundary resetKey={activeSurface}>
      <AppShell
      activeSurface={activeSurface}
      onNavigate={setActiveSurface}
      displayName={displayName}
      onSignOut={signOut}
    >
      {surface}
      </AppShell>
    </AppErrorBoundary>
  )
}
