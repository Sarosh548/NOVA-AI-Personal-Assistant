import { buildApiUrl } from "../app/config"
import type { ApiError, TokenResponse } from "./types"

const ACCESS_TOKEN_KEY = "nova.access_token"
const REFRESH_TOKEN_KEY = "nova.refresh_token"
const SESSION_EXPIRED_EVENT = "nova:session-expired"

let refreshPromise: Promise<TokenResponse> | null = null

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

function notifySessionExpired(): void {
  if (typeof window === "undefined") return
  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT))
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

async function performRequest<T>(
  path: string,
  options: RequestInit,
): Promise<T> {
  let url: string

  try {
    url = buildApiUrl(path)
  } catch (error) {
    throw new ApiRequestError(
      0,
      error instanceof Error
        ? error.message
        : "NOVA API endpoint is not configured.",
    )
  }

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

  let response: Response

  try {
    response = await fetch(url, {
      ...options,
      headers,
    })
  } catch {
    throw new ApiRequestError(
      0,
      "NOVA could not reach the service. Check your connection and try again.",
    )
  }

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

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  return performRequest(path, options)
}

async function rotateAccessSession(): Promise<TokenResponse> {
  const refreshToken = getRefreshToken()

  if (!refreshToken) {
    throw new ApiRequestError(401, "No refresh session is available.")
  }

  const response = await performRequest<TokenResponse>("/auth/refresh", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      refresh_token: refreshToken,
    }),
  })

  persistTokenResponse(response)
  return response
}

export async function refreshAccessToken(): Promise<TokenResponse> {
  if (refreshPromise) {
    return refreshPromise
  }

  refreshPromise = rotateAccessSession()

  try {
    return await refreshPromise
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 401) {
      clearStoredSession()
      notifySessionExpired()
    }
    throw error
  } finally {
    refreshPromise = null
  }
}

export async function apiRequestWithRefresh<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const accessTokenAtRequestStart = getAccessToken()

  try {
    return await performRequest<T>(path, options)
  } catch (error) {
    if (
      !(error instanceof ApiRequestError) ||
      error.status !== 401 ||
      !getRefreshToken()
    ) {
      throw error
    }

    const latestAccessToken = getAccessToken()

    if (
      accessTokenAtRequestStart &&
      latestAccessToken &&
      latestAccessToken !== accessTokenAtRequestStart
    ) {
      return performRequest<T>(path, options)
    }

    await refreshAccessToken()
    return performRequest<T>(path, options)
  }
}
