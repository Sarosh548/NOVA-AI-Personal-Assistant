import {
  apiRequest,
  apiRequestWithRefresh,
  clearStoredSession,
  persistTokenResponse,
} from "./client"
import type {
  NovaUser,
  RegisterResponse,
  TokenResponse,
} from "./types"

export async function register(params: {
  identifier: string
  password: string
  display_name?: string
}): Promise<RegisterResponse> {
  return apiRequest<RegisterResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify(params),
  })
}

export async function verifyEmail(params: {
  email: string
  code: string
}): Promise<NovaUser> {
  return apiRequest<NovaUser>("/auth/verify-email", {
    method: "POST",
    body: JSON.stringify(params),
  })
}

export async function resendVerification(email: string): Promise<{
  message: string
}> {
  return apiRequest<{ message: string }>("/auth/resend-verification", {
    method: "POST",
    body: JSON.stringify({ email }),
  })
}

export async function requestPasswordReset(email: string): Promise<{
  message: string
}> {
  return apiRequest<{ message: string }>("/auth/request-password-reset", {
    method: "POST",
    body: JSON.stringify({ email }),
  })
}

export async function resetPassword(params: {
  email: string
  code: string
  new_password: string
}): Promise<NovaUser> {
  return apiRequest<NovaUser>("/auth/reset-password", {
    method: "POST",
    body: JSON.stringify(params),
  })
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
