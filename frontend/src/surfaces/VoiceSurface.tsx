import { lazy, Suspense } from "react"

const LiveKitVoiceSurface = lazy(async () => {
  const module = await import("./LiveKitVoiceSurface")
  return { default: module.LiveKitVoiceSurface }
})

const GeminiLiveVoiceSurface = lazy(async () => {
  const module = await import("./GeminiLiveVoiceSurface")
  return { default: module.GeminiLiveVoiceSurface }
})

// Public GitHub Pages uses constrained ephemeral-token Gemini Live; local
// development keeps the tested LiveKit WebRTC voice implementation.
const useCloudGeminiVoice =
  import.meta.env.VITE_NOVA_VOICE_TRANSPORT?.trim().toLowerCase() === "gemini"

export function VoiceSurface({
  onOpenConversation,
}: {
  onOpenConversation: () => void
}) {
  return (
    <Suspense
      fallback={
        <div className="voice-shell livekit-voice-shell" role="status" aria-live="polite">
          <div className="voice-brand-state">
            <div className="voice-brand-label">NOVA - VOICE</div>
            <div className="voice-live-state connecting">PREPARING VOICE</div>
          </div>
        </div>
      }
    >
      {useCloudGeminiVoice ? (
        <GeminiLiveVoiceSurface onOpenConversation={onOpenConversation} cloudMode />
      ) : (
        <LiveKitVoiceSurface onOpenConversation={onOpenConversation} />
      )}
    </Suspense>
  )
}
