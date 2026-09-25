import { Icon } from "../components/Icon"

type HomeSurfaceProps = {
  onOpenConversation: () => void
  onOpenVoice: () => void
}

export function HomeSurface({
  onOpenConversation,
  onOpenVoice,
}: HomeSurfaceProps) {
  return (
    <div className="content-shell">
      <section className="hero-grid">
        <div>
          <div className="eyebrow">
            <span className="eyebrow-dot" />
            PERSONAL COMMAND CENTER
          </div>
          <h1>Your day, with less friction.</h1>
          <p className="hero-copy">
            NOVA is being shaped as a voice-first executive assistant:
            conversation, planning, memory, research, and authorized action in
            one place.
          </p>

          <div className="hero-actions">
            <button className="primary-action" type="button" onClick={onOpenVoice}>
              <Icon name="mic" size={18} />
              Start with NOVA
            </button>
            <button className="secondary-action" type="button" onClick={onOpenConversation}>
              Explore conversation
              <Icon name="arrow" size={17} />
            </button>
          </div>
        </div>

        <div className="orb-card" aria-label="NOVA assistant status">
          <div className="orb-glow orb-glow-one" />
          <div className="orb-glow orb-glow-two" />
          <div className="nova-orb">
            <div className="orb-core">
              <Icon name="spark" size={34} />
            </div>
          </div>
          <div className="orb-status">
            <span className="status-pill">Ready</span>
            <span className="orb-caption">Conversation surface next</span>
          </div>
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div>
            <div className="section-kicker">QUICK ACTIONS</div>
            <h2>Move from intent to action.</h2>
          </div>
          <span className="section-note">Foundation UI</span>
        </div>

        <div className="action-grid">
          <ActionCard
            icon="message"
            title="Talk to NOVA"
            description="Open the conversation workspace."
            onClick={onOpenVoice}
          />
          <ActionCard
            icon="check"
            title="Create a task"
            description="Capture something you want NOVA to handle."
          />
          <ActionCard
            icon="bell"
            title="Set a reminder"
            description="Keep future follow-ups in one place."
          />
          <ActionCard
            icon="calendar"
            title="Plan the day"
            description="Bring schedule, priorities, and timing together."
          />
        </div>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div>
            <div className="section-kicker">TODAY</div>
            <h2>Personal context will live here.</h2>
          </div>
        </div>

        <div className="context-panel">
          <div className="context-icon">
            <Icon name="spark" size={19} />
          </div>
          <div>
            <div className="context-title">
              Your live dashboard is intentionally empty for now.
            </div>
            <p className="context-copy">
              This foundation keeps the client shell separate from backend
              business logic. The next milestones will connect authentication,
              conversations, tasks, reminders, calendar, memory, and realtime
              voice to their existing APIs.
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}

function ActionCard({
  icon,
  title,
  description,
  onClick,
}: {
  icon: "message" | "check" | "bell" | "calendar"
  title: string
  description: string
  onClick?: () => void
}) {
  return (
    <button className="action-card" type="button" onClick={onClick}>
      <div className="action-card-icon">
        <Icon name={icon} size={19} />
      </div>
      <div className="action-card-content">
        <div className="action-card-title">{title}</div>
        <div className="action-card-copy">{description}</div>
      </div>
      <Icon name="arrow" size={17} />
    </button>
  )
}
