import type { SurfaceKey } from "../app/navigation"
import { Icon } from "../components/Icon"

type PlaceholderSurfaceProps = {
  label: SurfaceKey
  onBackHome: () => void
}

export function PlaceholderSurface({
  label,
  onBackHome,
}: PlaceholderSurfaceProps) {
  return (
    <div className="placeholder-shell">
      <div className="placeholder-card">
        <div className="placeholder-icon">
          <Icon name="spark" size={22} />
        </div>
        <div className="section-kicker">SURFACE SCAFFOLD</div>
        <h1>{label}</h1>
        <p>
          This surface is part of the NOVA product shell. Its real
          backend-connected workflow will be implemented as a separate
          milestone.
        </p>
        <button className="secondary-action" type="button" onClick={onBackHome}>
          Back to Home
          <Icon name="arrow" size={17} />
        </button>
      </div>
    </div>
  )
}
