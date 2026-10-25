import type { ChangeEvent } from "react"

export type VoiceTransport = "gemini" | "legacy" | "openai"

export function VoiceTransportControl({
  value,
  onChange,
}: {
  value: VoiceTransport
  onChange: (value: VoiceTransport) => void
}) {
  const handleChange = (event: ChangeEvent<HTMLSelectElement>) => {
    onChange(event.target.value as VoiceTransport)
  }

  return (
    <div className="voice-engine-setting">
      <label htmlFor="nova-voice-engine">Voice engine</label>
      <select
        id="nova-voice-engine"
        value={value}
        onChange={handleChange}
      >
        <option value="gemini">Gemini Live · recommended free tier</option>
        <option value="legacy">Classic NOVA voice</option>
        <option value="openai">OpenAI Realtime · quota required</option>
      </select>
      <p>
        Gemini's free tier has usage limits. OpenAI Realtime needs available
        API quota. Your choice stays saved when you leave and return to Voice.
      </p>
    </div>
  )
}
