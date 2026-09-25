import { buildApiUrl } from "../app/config"
import type { ApiError, TokenResponse } from "./types"

const ACCESS_TOKEN_KEY = "nova.access_token"
const REFRESH_TOKEN_KEY = "nova.refresh_token"

export class ApiRequestError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = "ApiRequestError"
    this.status = status
    this.detail = detail
  }
}

function readStoredValue(key: string): string | null {
  if (typeof window === "undefined") {
    return null
  }

  return window.sessionStorage.getItem(key)
}

function writeStoredValue(key: string, value: string): void {
  window.sessionStorage.setItem(key, value)
}

function removeStoredValue(key: string): void {
  window.sessionStorage.removeItem(key)
}

export function getAccessToken(): string | null {
  return readStoredValue(ACCESS_TOKEN_KEY)
}

export function getRefreshToken(): string | null {
  return readStoredValue(REFRESH_TOKEN_KEY)
}

export function persistTokenResponse(response: TokenResponse): void {
  writeStoredValue(ACCESS_TOKEN_KEY, response.access_token)
  writeStoredValue(REFRESH_TOKEN_KEY, response.refresh_token)
}

export function clearStoredSession(): void {
  removeStoredValue(ACCESS_TOKEN_KEY)
  removeStoredValue(REFRESH_TOKEN_KEY)
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as Partial<ApiError>

    if (typeof payload.detail === "string") {
      return payload.detail
    }

    if (Array.isArray(payload.detail)) {
      return "The request was not accepted. Please check the entered values."
    }
  } catch {
    // Fall through to a status-based message.
  }

  return response.statusText || "Request failed."
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers)
  const accessToken = getAccessToken()

  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json")
  }

  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }

  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`)
  }

  const response = await fetch(buildApiUrl(path), {
    ...options,
    headers,
  })

  if (!response.ok) {
    throw new ApiRequestError(
      response.status,
      await parseErrorDetail(response),
    )
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

export async function refreshAccessToken(): Promise<TokenResponse> {
  const refreshToken = getRefreshToken()

  if (!refreshToken) {
    throw new ApiRequestError(401, "No refresh session is available.")
  }

  const response = await fetch(buildApiUrl("/auth/refresh"), {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      refresh_token: refreshToken,
    }),
  })

  if (!response.ok) {
    throw new ApiRequestError(
      response.status,
      await parseErrorDetail(response),
    )
  }

  const tokenResponse = (await response.json()) as TokenResponse
  persistTokenResponse(tokenResponse)

  return tokenResponse
}

export async function apiRequestWithRefresh<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  try {
    return await apiRequest<T>(path, options)
  } catch (error) {
    if (
      !(error instanceof ApiRequestError) ||
      error.status !== 401 ||
      !getRefreshToken()
    ) {
      throw error
    }

    await refreshAccessToken()
    return apiRequest<T>(path, options)
  }
}
