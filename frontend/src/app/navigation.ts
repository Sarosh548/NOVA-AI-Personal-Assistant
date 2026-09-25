export type SurfaceKey =
  | "Home"
  | "Conversation"
  | "Tasks"
  | "Reminders"
  | "Calendar"
  | "Activity"
  | "Memory"
  | "Knowledge"
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

export type NavigationItem = {
  label: SurfaceKey
  icon: IconName
  group: "workspace" | "system"
}

export const navigation: NavigationItem[] = [
  { label: "Home", icon: "home", group: "workspace" },
  { label: "Conversation", icon: "message", group: "workspace" },
  { label: "Tasks", icon: "check", group: "workspace" },
  { label: "Reminders", icon: "bell", group: "workspace" },
  { label: "Calendar", icon: "calendar", group: "workspace" },
  { label: "Activity", icon: "activity", group: "workspace" },
  { label: "Memory", icon: "brain", group: "system" },
  { label: "Knowledge", icon: "book", group: "system" },
  { label: "Settings", icon: "settings", group: "system" },
]
