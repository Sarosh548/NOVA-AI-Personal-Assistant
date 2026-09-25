import {
  apiRequest,
  apiRequestWithRefresh,
  clearStoredSession,
  persistTokenResponse,
} from "./client"
import type { NovaUser, TokenResponse } from "./types"

export async function register(params: {
  identifier: string
  password: string
  display_name?: string
}): Promise<TokenResponse> {
  const response = await apiRequest<TokenResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify(params),
  })

  persistTokenResponse(response)
  return response
}

export async function login(params: {
  identifier: string
  password: string
}): Promise<TokenResponse> {
  const form = new URLSearchParams()
  form.set("username", params.identifier)
  form.set("password", params.password)
  form.set("grant_type", "password")

  const response = await apiRequest<TokenResponse>("/auth/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: form.toString(),
  })

  persistTokenResponse(response)
  return response
}

export async function getCurrentUser(): Promise<NovaUser> {
  return apiRequestWithRefresh<NovaUser>("/auth/me")
}

export async function logout(): Promise<void> {
  try {
    await apiRequest<void>("/auth/logout", {
      method: "POST",
    })
  } finally {
    clearStoredSession()
  }
}
