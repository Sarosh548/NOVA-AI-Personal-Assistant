export type VoiceLanguage = "multi" | "en-US" | "ur" | "hi"

const VOICE_LANGUAGE_STORAGE_KEY = "nova.voice.language"

const ALLOWED_VOICE_LANGUAGES: readonly VoiceLanguage[] = [
  "multi",
  "en-US",
  "ur",
  "hi",
]

export function getVoiceLanguagePreference(): VoiceLanguage {
  if (typeof window !== "undefined") {
    try {
      const saved = window.localStorage.getItem(VOICE_LANGUAGE_STORAGE_KEY)
      if (ALLOWED_VOICE_LANGUAGES.includes(saved as VoiceLanguage)) {
        return saved as VoiceLanguage
      }
    } catch {
      // Storage can be unavailable in private or restricted browser contexts.
    }
  }

  return "multi"
}

export function setVoiceLanguagePreference(language: VoiceLanguage): void {
  if (!ALLOWED_VOICE_LANGUAGES.includes(language)) return

  try {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(VOICE_LANGUAGE_STORAGE_KEY, language)
    }
  } catch {
    // The selected value still applies to the current component if storage is blocked.
  }
}

export function detectVoiceTextLanguage(text: string): "en" | "ur" | "hi" {
  if (/[؀-ۿݐ-ݿ]/u.test(text)) return "ur"
  if (/[ऀ-ॿ]/u.test(text)) return "hi"

  const markers = new Set([
    "acha", "abhi", "aap", "batao", "btao", "bhi", "chahiye",
    "hai", "hain", "haan", "han", "ho", "kaise", "kab", "kahan",
    "kar", "kro", "kr", "krna", "kya", "kyun", "main", "mera",
    "meri", "mujhe", "mja", "nahi", "nahin", "rha", "raha",
    "rhi", "yr", "yaar", "tum",
  ])
  const words = new Set(
    text.toLowerCase().split(/\s+/u).map((word) => word.replace(/[^\p{L}\p{N}]/gu, "")),
  )
  let matches = 0
  for (const word of words) {
    if (markers.has(word)) matches += 1
  }

  return matches >= 2 ? "ur" : "en"
}
