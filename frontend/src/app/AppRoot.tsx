import { useState } from "react"

import { AuthScreen } from "../auth/AuthScreen"
import { useAuth } from "../auth/AuthProvider"
import { ConversationSurface } from "../surfaces/ConversationSurface"
import { HomeSurface } from "../surfaces/HomeSurface"
import { PlaceholderSurface } from "../surfaces/PlaceholderSurface"
import { AppShell } from "../layout/AppShell"
import type { SurfaceKey } from "./navigation"

export function AppRoot() {
  const { status, user, signOut } = useAuth()
  const [activeSurface, setActiveSurface] = useState<SurfaceKey>("Home")

  if (status === "loading") {
    return <div className="auth-loading" aria-live="polite"><div className="brand-mark"><span className="loading-pulse" /></div><span>Loading NOVA…</span></div>
  }

  if (status === "unauthenticated") return <AuthScreen />

  const displayName = user?.display_name?.trim() || "NOVA user"

  return (
    <AppShell activeSurface={activeSurface} onNavigate={setActiveSurface} displayName={displayName} onSignOut={signOut}>
      {activeSurface === "Home" ? (
        <HomeSurface onOpenConversation={() => setActiveSurface("Conversation")} />
      ) : activeSurface === "Conversation" ? (
        <ConversationSurface />
      ) : (
        <PlaceholderSurface label={activeSurface} onBackHome={() => setActiveSurface("Home")} />
      )}
    </AppShell>
  )
}
