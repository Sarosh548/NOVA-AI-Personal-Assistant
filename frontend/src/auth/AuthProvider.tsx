import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"

import {
  ApiRequestError,
  clearStoredSession,
  getRefreshToken,
  SESSION_EXPIRED_EVENT,
} from "../api/client"
import { getCurrentUser, login, logout, register } from "../api/auth"
import type { NovaUser } from "../api/types"

type AuthStatus =
  | "loading"
  | "authenticated"
  | "unauthenticated"

type AuthContextValue = {
  status: AuthStatus
  user: NovaUser | null
  error: string | null
  signIn: (identifier: string, password: string) => Promise<void>
  signUp: (
    identifier: string,
    password: string,
    displayName: string,
  ) => Promise<void>
  signOut: () => Promise<void>
  retrySessionRestore: () => Promise<void>
  clearError: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading")
  const [user, setUser] = useState<NovaUser | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSessionExpired = useCallback(() => {
    clearStoredSession()
    setUser(null)
    setStatus("unauthenticated")
    setError("Your NOVA session has expired. Please sign in again.")
  }, [])

  useEffect(() => {
    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired)
    return () =>
      window.removeEventListener(
        SESSION_EXPIRED_EVENT,
        handleSessionExpired,
      )
  }, [handleSessionExpired])

  const restoreSession = useCallback(async () => {
    if (!getRefreshToken()) {
      setStatus("unauthenticated")
      return
    }

    try {
      const currentUser = await getCurrentUser()
      setUser(currentUser)
      setStatus("authenticated")
      setError(null)
    } catch (error) {
      if (error instanceof ApiRequestError && error.status >= 500) {
        setStatus("unauthenticated")
        setError("NOVA could not reach the service. Please try again.")
        return
      }

      if (error instanceof ApiRequestError && error.status === 0) {
        setStatus("unauthenticated")
        setError("NOVA could not reach the service. Check your connection and try again.")
        return
      }

      clearStoredSession()
      setUser(null)
      setStatus("unauthenticated")

      if (error instanceof ApiRequestError && error.status >= 400) {
        setError(error.detail)
      }
    }
  }, [])

  useEffect(() => {
    void restoreSession()
  }, [restoreSession])

  const retrySessionRestore = useCallback(async () => {
    setError(null)
    setStatus("loading")
    await restoreSession()
  }, [restoreSession])

  const signIn = useCallback(
    async (identifier: string, password: string) => {
      setError(null)

      try {
        const response = await login({ identifier, password })
        setUser(response.user)
        setStatus("authenticated")
      } catch (error) {
        setStatus("unauthenticated")
        setError(
          error instanceof ApiRequestError
            ? error.detail
            : "Sign in failed. Please try again.",
        )
        throw error
      }
    },
    [],
  )

  const signUp = useCallback(
    async (
      identifier: string,
      password: string,
      displayName: string,
    ) => {
      setError(null)

      try {
        const response = await register({
          identifier,
          password,
          display_name: displayName.trim() || undefined,
        })
        setUser(response.user)
        setStatus("authenticated")
      } catch (error) {
        setStatus("unauthenticated")
        setError(
          error instanceof ApiRequestError
            ? error.detail
            : "Account creation failed. Please try again.",
        )
        throw error
      }
    },
    [],
  )

  const signOut = useCallback(async () => {
    setError(null)

    try {
      await logout()
    } finally {
      setUser(null)
      setStatus("unauthenticated")
    }
  }, [])

  const clearError = useCallback(() => setError(null), [])

  const value = useMemo(
    () => ({
      status,
      user,
      error,
      signIn,
      signUp,
      signOut,
      retrySessionRestore,
      clearError,
    }),
    [
      status,
      user,
      error,
      signIn,
      signUp,
      signOut,
      retrySessionRestore,
      clearError,
    ],
  )

  return (
    <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)

  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider.")
  }

  return context
}
