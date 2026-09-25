import { useState } from "react"

import type { SurfaceKey } from "./app/navigation"
import { AppShell } from "./layout/AppShell"
import { HomeSurface } from "./surfaces/HomeSurface"
import { PlaceholderSurface } from "./surfaces/PlaceholderSurface"

function App() {
  const [activeSurface, setActiveSurface] = useState<SurfaceKey>("Home")

  const handleNavigate = (surface: SurfaceKey) => {
    setActiveSurface(surface)
  }

  return (
    <AppShell
      activeSurface={activeSurface}
      onNavigate={handleNavigate}
    >
      {activeSurface === "Home" ? (
        <HomeSurface
          onOpenConversation={() => handleNavigate("Conversation")}
        />
      ) : (
        <PlaceholderSurface
          label={activeSurface}
          onBackHome={() => handleNavigate("Home")}
        />
      )}
    </AppShell>
  )
}

export default App
