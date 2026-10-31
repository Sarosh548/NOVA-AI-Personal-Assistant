import { buildApiUrl } from "../app/config"
import type { ApiError, TokenResponse } from "./types"

const ACCESS_TOKEN_KEY = "nova.access_token"
const REFRESH_TOKEN_KEY = "nova.refresh_token"
const REFRESH_CLIENT_KEY = "nova.refresh_client_key"
export const SESSION_EXPIRED_EVENT = "nova:session-expired"

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

function ensureRefreshClientKey(): string {
  let clientKey = window.localStorage.getItem(REFRESH_CLIENT_KEY)
  if (!clientKey) {
    clientKey = window.crypto.randomUUID()
    window.localStorage.setItem(REFRESH_CLIENT_KEY, clientKey)
  }
  return clientKey
}

export function persistTokenResponse(response: TokenResponse): void {
  ensureRefreshClientKey()
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
  timeoutMs?: number,
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
  const controller = timeoutMs && timeoutMs > 0 ? new AbortController() : null
  let timedOut = false
  let timeoutHandle: ReturnType<typeof setTimeout> | undefined
  const externalSignal = options.signal
  const abortFromExternalSignal = () => controller?.abort(externalSignal?.reason)

  if (controller && timeoutMs) {
    timeoutHandle = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)
    if (externalSignal?.aborted) {
      controller.abort(externalSignal.reason)
    } else {
      externalSignal?.addEventListener("abort", abortFromExternalSignal, { once: true })
    }
  }

  try {
    response = await fetch(url, {
      ...options,
      headers,
      ...(controller ? { signal: controller.signal } : {}),
    })
  } catch {
    if (timedOut) {
      throw new ApiRequestError(
        0,
        "NOVA took too long to respond. Check the conversation before retrying; the same request ID is reused safely.",
      )
    }

    throw new ApiRequestError(
      0,
      "NOVA could not reach the service. Check your connection and try again.",
    )
  } finally {
    if (timeoutHandle !== undefined) clearTimeout(timeoutHandle)
    externalSignal?.removeEventListener("abort", abortFromExternalSignal)
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
  timeoutMs?: number,
): Promise<T> {
  return performRequest(path, options, timeoutMs)
}

async function getRefreshRotationId(refreshToken: string): Promise<string> {
  if (typeof window === "undefined" || !window.crypto?.subtle) {
    throw new ApiRequestError(0, "Secure refresh recovery is unavailable in this browser.")
  }

  const clientKey = window.navigator.locks
    ? await window.navigator.locks.request(
        "nova-refresh-client-key",
        () => ensureRefreshClientKey(),
      )
    : ensureRefreshClientKey()

  const digest = await window.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(`${clientKey}:${refreshToken}`),
  )
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")
}

async function rotateAccessSession(): Promise<TokenResponse> {
  const refreshToken = getRefreshToken()

  if (!refreshToken) {
    throw new ApiRequestError(401, "No refresh session is available.")
  }

  const rotationId = await getRefreshRotationId(refreshToken)
  const response = await performRequest<TokenResponse>("/auth/refresh", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      refresh_token: refreshToken,
      rotation_id: rotationId,
    }),
  })

  persistTokenResponse(response)
  return response
}

export async function refreshAccessToken(): Promise<TokenResponse> {
  if (!refreshPromise) {
    refreshPromise = rotateAccessSession()
      .catch((error) => {
        if (error instanceof ApiRequestError && error.status === 401) {
          clearStoredSession()
          notifySessionExpired()
        }
        throw error
      })
      .finally(() => {
        refreshPromise = null
      })
  }

  return refreshPromise
}

export async function apiRequestWithRefresh<T>(
  path: string,
  options: RequestInit = {},
  timeoutMs?: number,
): Promise<T> {
  const accessTokenAtRequestStart = getAccessToken()

  try {
    return await performRequest<T>(path, options, timeoutMs)
  } catch (error) {
    if (
      !(error instanceof ApiRequestError) ||
      error.status !== 401
    ) {
      throw error
    }

    if (!getRefreshToken()) {
      clearStoredSession()
      notifySessionExpired()
      throw error
    }

    const latestAccessToken = getAccessToken()

    if (
      accessTokenAtRequestStart &&
      latestAccessToken &&
      latestAccessToken !== accessTokenAtRequestStart
    ) {
      return performRequest<T>(path, options, timeoutMs)
    }

    await refreshAccessToken()
    return performRequest<T>(path, options, timeoutMs)
  }
}
