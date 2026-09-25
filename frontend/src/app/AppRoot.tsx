import { AppShell } from "../layout/AppShell"
import { HomeSurface } from "../surfaces/HomeSurface"
import { PlaceholderSurface } from "../surfaces/PlaceholderSurface"
import { AuthScreen } from "../auth/AuthScreen"
import { useAuth } from "../auth/AuthProvider"
import { useState } from "react"
import type { SurfaceKey } from "./navigation"

export function AppRoot() {
  const { status } = useAuth()
  const [activeSurface, setActiveSurface] = useState<SurfaceKey>("Home")

  if (status === "loading") {
    return (
      <div className="auth-loading" aria-live="polite">
        <div className="brand-mark">
          <span className="loading-pulse" />
        </div>
        <span>Loading NOVA…</span>
      </div>
    )
  }

  if (status === "unauthenticated") {
    return <AuthScreen />
  }

  return (
    <AppShell
      activeSurface={activeSurface}
      onNavigate={setActiveSurface}
    >
      {activeSurface === "Home" ? (
        <HomeSurface
          onOpenConversation={() => setActiveSurface("Conversation")}
        />
      ) : (
        <PlaceholderSurface
          label={activeSurface}
          onBackHome={() => setActiveSurface("Home")}
        />
      )}
    </AppShell>
  )
}
