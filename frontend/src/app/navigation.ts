export type SurfaceKey =
  | "Home"
  | "Conversation"
  | "Voice"
  | "Tasks"
  | "Reminders"
  | "Calendar"
  | "Activity"
  | "Memory"
  | "Knowledge"
  | "Control Center"
  | "Settings"

export type IconName =
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
  | "logout"
  | "eye"
  | "eye-off"
  | "menu"
  | "close"
  | "edit"
  | "trash"
  | "search"

export type NavigationItem = {
  label: SurfaceKey
  icon: IconName
  group: "workspace" | "system"
}

export const navigation: NavigationItem[] = [
  { label: "Home", icon: "home", group: "workspace" },
  { label: "Conversation", icon: "message", group: "workspace" },
  { label: "Voice", icon: "mic", group: "workspace" },
  { label: "Tasks", icon: "check", group: "workspace" },
  { label: "Reminders", icon: "bell", group: "workspace" },
  { label: "Calendar", icon: "calendar", group: "workspace" },
  { label: "Activity", icon: "activity", group: "workspace" },
  { label: "Memory", icon: "brain", group: "system" },
  { label: "Knowledge", icon: "book", group: "system" },
  { label: "Control Center", icon: "settings", group: "system" },
  { label: "Settings", icon: "settings", group: "system" },
]


export function surfaceHash(surface: SurfaceKey): string {
  return (
    "#/" +
    surface
      .toLowerCase()
      .replace(/\s+/g, "-")
  )
}

export function surfaceFromHash(hash: string): SurfaceKey | null {
  const normalized = hash.replace(/^#\/?/, "").trim().toLowerCase()
  if (!normalized) return "Home"

  return (
    navigation.find(
      (item) =>
        item.label.toLowerCase().replace(/\s+/g, "-") === normalized,
    )?.label ?? null
  )
}
