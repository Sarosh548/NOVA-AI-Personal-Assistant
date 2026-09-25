const configuredApiBaseUrl = import.meta.env.VITE_NOVA_API_BASE_URL?.trim()

export const isApiBaseUrlConfigured =
  Boolean(configuredApiBaseUrl) || import.meta.env.DEV

export const API_BASE_URL =
  configuredApiBaseUrl ||
  (import.meta.env.DEV ? "http://127.0.0.1:8000" : "")

export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`

  if (!API_BASE_URL) {
    throw new Error(
      "NOVA API endpoint is not configured for this deployment.",
    )
  }

  return `${API_BASE_URL}${normalizedPath}`
}
