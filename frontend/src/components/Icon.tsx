import type { IconName } from "../app/navigation"

type IconProps = {
  name: IconName
  size?: number
}

export function Icon({ name, size = 20 }: IconProps) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  }

  switch (name) {
    case "spark":
      return (
        <svg {...common}>
          <path d="M12 3l1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3z" />
          <path d="M19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16z" />
        </svg>
      )
    case "home":
      return (
        <svg {...common}>
          <path d="M3.5 10.7L12 3.8l8.5 6.9" />
          <path d="M5.5 9.5v10.7h13V9.5" />
          <path d="M9.5 20.2v-6h5v6" />
        </svg>
      )
    case "message":
      return (
        <svg {...common}>
          <path d="M5 5.5h14v9H9l-4 3v-12z" />
          <path d="M8 9h8M8 12h5" />
        </svg>
      )
    case "check":
      return (
        <svg {...common}>
          <rect x="4" y="4" width="16" height="16" rx="4" />
          <path d="M8 12.2l2.5 2.5 5.5-5.7" />
        </svg>
      )
    case "bell":
      return (
        <svg {...common}>
          <path d="M6.5 10a5.5 5.5 0 0111 0v3.2l1.5 2.3H5l1.5-2.3V10z" />
          <path d="M10 18h4" />
        </svg>
      )
    case "calendar":
      return (
        <svg {...common}>
          <rect x="4" y="5.5" width="16" height="14" rx="3" />
          <path d="M8 3.5v4M16 3.5v4M4 10h16M8 13h3M13 13h3M8 16h3" />
        </svg>
      )
    case "activity":
      return (
        <svg {...common}>
          <path d="M4 14h3l2-7 4 12 2.2-7H20" />
        </svg>
      )
    case "brain":
      return (
        <svg {...common}>
          <path d="M9 5.2A3.2 3.2 0 006 8.4v.2A3.5 3.5 0 006.5 15 3.2 3.2 0 009 18.1V5.2z" />
          <path d="M15 5.2a3.2 3.2 0 013 3.2v.2a3.5 3.5 0 01-.5 6.4 3.2 3.2 0 01-2.5 3.1V5.2z" />
          <path d="M9 9h2M13 9h2M9 13h2M13 13h2M12 5v14" />
        </svg>
      )
    case "book":
      return (
        <svg {...common}>
          <path d="M4 5.5a2 2 0 012-2h5v16H6a2 2 0 01-2-2v-12z" />
          <path d="M20 5.5a2 2 0 00-2-2h-5v16h5a2 2 0 002-2v-12z" />
        </svg>
      )
    case "settings":
      return (
        <svg {...common}>
          <path d="M12 8.5a3.5 3.5 0 100 7 3.5 3.5 0 000-7z" />
          <path d="M19 13.2v-2.4l-2-.6a6.4 6.4 0 00-.8-1.8l1-1.8-1.7-1.7-1.8 1a6.4 6.4 0 00-1.8-.8l-.6-2h-2.4l-.6 2a6.4 6.4 0 00-1.8.8l-1.8-1L4.1 6.6l1 1.8a6.4 6.4 0 00-.8 1.8l-2 .6v2.4l2 .6c.2.7.4 1.2.8 1.8l-1 1.8 1.7 1.7 1.8-1c.6.4 1.2.7 1.8.8l.6 2h2.4l.6-2a6.4 6.4 0 001.8-.8l1.8 1 1.7-1.7-1-1.8c.4-.6.7-1.2-.8-1.8l2-.6z" />
        </svg>
      )
    case "plus":
      return (
        <svg {...common}>
          <path d="M12 5v14M5 12h14" />
        </svg>
      )
    case "arrow":
      return (
        <svg {...common}>
          <path d="M5 12h13M13 6l6 6-6 6" />
        </svg>
      )
    case "mic":
      return (
        <svg {...common}>
          <rect x="8.5" y="3.5" width="7" height="11" rx="3.5" />
          <path d="M6 11.5a6 6 0 0012 0M12 17.5v3M9 20.5h6" />
        </svg>
      )
    case "eye":
      return (
        <svg {...common}>
          <path d="M2.7 12s3.4-5 9.3-5 9.3 5 9.3 5-3.4 5-9.3 5-9.3-5-9.3-5z" />
          <circle cx="12" cy="12" r="2.2" />
        </svg>
      )
    case "eye-off":
      return (
        <svg {...common}>
          <path d="M3 3l18 18" />
          <path d="M10.5 6.9A9.8 9.8 0 0112 7c5.9 0 9.3 5 9.3 5a15 15 0 01-3.1 3.4M6.2 6.6C3.9 8.1 2.7 12 2.7 12s3.4 5 9.3 5c1 0 1.9-.2 2.7-.4" />
          <path d="M9.9 9.9a3 3 0 004.2 4.2" />
        </svg>
      )
    case "logout":
      return (
        <svg {...common}>
          <path d="M10 5H6.5a2 2 0 00-2 2v10a2 2 0 002 2H10" />
          <path d="M14 8l4 4-4 4M18 12H9" />
        </svg>
      )
  }
}
