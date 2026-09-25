import { useEffect, useRef, useState, type FormEvent } from "react"

import { isApiBaseUrlConfigured } from "../app/config"
import { getRefreshToken } from "../api/client"
import { Icon } from "../components/Icon"
import { useAuth } from "./AuthProvider"

type AuthMode = "sign-in" | "sign-up"

export function AuthScreen() {
  const { signIn, signUp, error, clearError, retrySessionRestore } = useAuth()
  const [mode, setMode] = useState<AuthMode>("sign-in")
  const [identifier, setIdentifier] = useState("")
  const [password, setPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [displayName, setDisplayName] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const identifierRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      identifierRef.current?.focus()
    })

    return () => window.cancelAnimationFrame(frame)
  }, [mode])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    clearError()

    if (!isApiBaseUrlConfigured) {
      return
    }

    setIsSubmitting(true)

    try {
      if (mode === "sign-in") {
        await signIn(identifier.trim(), password)
      } else {
        await signUp(identifier.trim(), password, displayName)
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const switchMode = () => {
    clearError()
    setPassword("")
    setShowPassword(false)
    setMode((current) =>
      current === "sign-in" ? "sign-up" : "sign-in",
    )
  }

  const isSignIn = mode === "sign-in"

  return (
    <main className="auth-screen">
      <div className="auth-background-glow auth-background-glow-one" />
      <div className="auth-background-glow auth-background-glow-two" />

      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-brand">
          <div className="brand-mark">
            <Icon name="spark" size={19} />
          </div>
          <div>
            <div className="brand-name">NOVA</div>
            <div className="brand-caption">Personal AI</div>
          </div>
        </div>

        <div className="auth-heading">
          <div className="section-kicker">
            {isSignIn ? "WELCOME BACK" : "CREATE YOUR NOVA"}
          </div>
          <h1 id="auth-title">
            {isSignIn ? "Continue with NOVA." : "Start your personal assistant."}
          </h1>
          <p>
            Your conversations, plans, memory, and authorized actions stay
            connected to your personal NOVA account.
          </p>
        </div>

        {!isApiBaseUrlConfigured && (
          <div className="auth-notice" role="status">
            <div className="auth-notice-title">NOVA service is not connected.</div>
            <div className="auth-notice-copy">
              This deployment needs a configured NOVA API endpoint before
              sign-in is available.
            </div>
          </div>
        )}

        <form
          className="auth-form"
          onSubmit={handleSubmit}
          aria-busy={isSubmitting}
        >
          {mode === "sign-up" && (
            <label>
              <span>Name</span>
              <input
                autoComplete="name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="Your name"
                maxLength={200}
              />
            </label>
          )}

          <label>
            <span>Email or username</span>
            <input
              ref={identifierRef}
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              value={identifier}
              onChange={(event) => setIdentifier(event.target.value)}
              placeholder="you@example.com"
              required
              maxLength={255}
            />
          </label>

          <label>
            <span>Password</span>
            <div className="password-field">
              <input
                type={showPassword ? "text" : "password"}
                autoComplete={isSignIn ? "current-password" : "new-password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="At least 8 characters"
                required
                minLength={8}
                maxLength={256}
              />
              <button
                className="password-toggle"
                type="button"
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-pressed={showPassword}
                onClick={() => setShowPassword((current) => !current)}
              >
                <Icon name={showPassword ? "eye-off" : "eye"} size={17} />
              </button>
            </div>
          </label>

          {error && (
            <div className="auth-error" role="alert">
              {error}
            </div>
          )}

          {error && getRefreshToken() && (
            <button
              className="secondary-action"
              type="button"
              onClick={() => void retrySessionRestore()}
            >
              Retry connection
            </button>
          )}

          <button
            className="primary-action auth-submit"
            type="submit"
            disabled={isSubmitting || !isApiBaseUrlConfigured}
          >
            {isSubmitting ? (
              <>
                <span className="auth-spinner" aria-hidden="true" />
                {isSignIn ? "Signing in…" : "Creating account…"}
              </>
            ) : (
              <>
                <Icon name="arrow" size={17} />
                {isSignIn ? "Sign in" : "Create account"}
              </>
            )}
          </button>
        </form>

        <div className="auth-switch">
          <span>
            {isSignIn ? "New to NOVA?" : "Already have a NOVA account?"}
          </span>
          <button type="button" onClick={switchMode}>
            {isSignIn ? "Create account" : "Sign in"}
          </button>
        </div>
      </section>

      <p className="auth-footer">
        Secure session · Personal workspace · Voice-first experience
      </p>
    </main>
  )
}
