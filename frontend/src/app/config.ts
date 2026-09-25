const configuredApiBaseUrl = import.meta.env.VITE_NOVA_API_BASE_URL?.trim()

export const API_BASE_URL =
  configuredApiBaseUrl || "http://127.0.0.1:8000"

export const isApiBaseUrlConfigured = Boolean(configuredApiBaseUrl)

export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`
  return `${API_BASE_URL}${normalizedPath}`
}
