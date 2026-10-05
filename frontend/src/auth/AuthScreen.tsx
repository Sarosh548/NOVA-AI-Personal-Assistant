import { useEffect, useRef, useState, type FormEvent } from "react"

import { isApiBaseUrlConfigured } from "../app/config"
import { getRefreshToken } from "../api/client"
import { Icon } from "../components/Icon"
import { useAuth } from "./AuthProvider"

type AuthMode =
  | "sign-in"
  | "sign-up"
  | "verify-email"
  | "forgot-password"
  | "reset-password"

export function AuthScreen() {
  const {
    signIn,
    signUp,
    verifyEmail,
    resendVerification,
    requestPasswordReset,
    resetPassword,
    error,
    clearError,
    retrySessionRestore,
  } = useAuth()
  const [mode, setMode] = useState<AuthMode>("sign-in")
  const [identifier, setIdentifier] = useState("")
  const [password, setPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [displayName, setDisplayName] = useState("")
  const [verificationCode, setVerificationCode] = useState("")
  const [verificationEmail, setVerificationEmail] = useState("")
  const [resetEmail, setResetEmail] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isResending, setIsResending] = useState(false)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const identifierRef = useRef<HTMLInputElement | null>(null)
  const verificationCodeRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      if (mode === "verify-email" || mode === "reset-password") {
        verificationCodeRef.current?.focus()
      } else {
        identifierRef.current?.focus()
      }
    })

    return () => window.cancelAnimationFrame(frame)
  }, [mode])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    clearError()
    setLocalError(null)
    setSuccessMessage(null)

    if (!isApiBaseUrlConfigured) {
      return
    }

    setIsSubmitting(true)

    try {
      if (mode === "sign-in") {
        await signIn(identifier.trim(), password)
      } else if (mode === "sign-up") {
        const email = identifier.trim().toLowerCase()
        await signUp(email, password, displayName)
        setVerificationEmail(email)
        setVerificationCode("")
        setPassword("")
        setShowPassword(false)
        setDisplayName("")
        setMode("verify-email")
        setSuccessMessage("We sent a 6-digit verification code to your email.")
      } else if (mode === "verify-email") {
        await verifyEmail(
          verificationEmail,
          verificationCode.trim(),
        )
        setIdentifier(verificationEmail)
        setVerificationCode("")
        setMode("sign-in")
        setSuccessMessage("Email verified. Sign in to continue.")
      } else if (mode === "forgot-password") {
        const email = identifier.trim().toLowerCase()
        await requestPasswordReset(email)
        setResetEmail(email)
        setVerificationCode("")
        setNewPassword("")
        setConfirmPassword("")
        setShowNewPassword(false)
        setShowConfirmPassword(false)
        setMode("reset-password")
        setSuccessMessage(
          "If an account exists for that email, a 6-digit reset code was sent.",
        )
      } else {
        if (newPassword !== confirmPassword) {
          setLocalError("New password and confirmation do not match.")
          return
        }

        await resetPassword(
          resetEmail,
          verificationCode.trim(),
          newPassword,
        )
        setIdentifier(resetEmail)
        setPassword("")
        setNewPassword("")
        setConfirmPassword("")
        setVerificationCode("")
        setShowNewPassword(false)
        setShowConfirmPassword(false)
        setMode("sign-in")
        setSuccessMessage("Password updated. Sign in with your new password.")
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const switchMode = () => {
    clearError()
    setLocalError(null)
    setSuccessMessage(null)
    setPassword("")
    setNewPassword("")
    setConfirmPassword("")
    setShowPassword(false)
    setShowNewPassword(false)
    setShowConfirmPassword(false)
    setVerificationCode("")

    setMode((current) => {
      if (current === "sign-in") return "sign-up"
      return "sign-in"
    })
  }

  const openForgotPassword = () => {
    clearError()
    setLocalError(null)
    setSuccessMessage(null)
    setPassword("")
    setShowPassword(false)
    setMode("forgot-password")
  }

  const handleBackToSignIn = () => {
    clearError()
    setLocalError(null)
    setSuccessMessage(null)
    setPassword("")
    setNewPassword("")
    setConfirmPassword("")
    setShowPassword(false)
    setShowNewPassword(false)
    setShowConfirmPassword(false)
    setVerificationCode("")
    setMode("sign-in")
  }

  const handleResend = async () => {
    clearError()
    setLocalError(null)
    setSuccessMessage(null)
    setIsResending(true)

    try {
      await resendVerification(verificationEmail)
      setSuccessMessage("A new verification code has been sent.")
    } finally {
      setIsResending(false)
    }
  }

  const isSignIn = mode === "sign-in"
  const isSignUp = mode === "sign-up"
  const isVerifyEmail = mode === "verify-email"
  const isForgotPassword = mode === "forgot-password"
  const isResetPassword = mode === "reset-password"
  const isPasswordEntry = isSignIn || isSignUp
  const visibleError = error ?? localError

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
            {isVerifyEmail || isResetPassword
              ? isVerifyEmail
                ? "VERIFY YOUR EMAIL"
                : "RESET YOUR PASSWORD"
              : isForgotPassword
                ? "PASSWORD RECOVERY"
                : isSignIn
                  ? "WELCOME BACK"
                  : "CREATE YOUR NOVA"}
          </div>
          <h1 id="auth-title">
            {isVerifyEmail
              ? "Check your inbox."
              : isForgotPassword
                ? "Forgot your password?"
                : isResetPassword
                  ? "Choose a new password."
                  : isSignIn
                    ? "Continue with NOVA."
                    : "Start your personal assistant."}
          </h1>
          <p>
            {isVerifyEmail
              ? "Enter the 6-digit code we sent to " + verificationEmail + "."
              : isForgotPassword
                ? "Enter your account email and NOVA will send a 6-digit recovery code."
                : isResetPassword
                  ? "Enter the code sent to " + resetEmail + " and choose a new password."
                  : "Your conversations, plans, memory, and authorized actions stay connected to your personal NOVA account."}
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
          aria-busy={isSubmitting || isResending}
        >
          {isSignUp && (
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

          {(isSignIn || isSignUp || isForgotPassword) && (
            <label>
              <span>{isSignIn ? "Email or username" : "Email"}</span>
              <input
                ref={identifierRef}
                type={isSignIn ? "text" : "email"}
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
          )}

          {(isVerifyEmail || isResetPassword) && (
            <label>
              <span>{isResetPassword ? "Reset code" : "Verification code"}</span>
              <input
                ref={verificationCodeRef}
                className="auth-verification-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={verificationCode}
                onChange={(event) =>
                  setVerificationCode(
                    event.target.value.replace(/\D/g, "").slice(0, 6),
                  )
                }
                placeholder="000000"
                pattern="\d{6}"
                minLength={6}
                maxLength={6}
                required
              />
            </label>
          )}

          {isPasswordEntry && (
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
          )}

          {isResetPassword && (
            <>
              <label>
                <span>New password</span>
                <div className="password-field">
                  <input
                    type={showNewPassword ? "text" : "password"}
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    placeholder="At least 8 characters"
                    required
                    minLength={8}
                    maxLength={256}
                  />
                  <button
                    className="password-toggle"
                    type="button"
                    aria-label={showNewPassword ? "Hide new password" : "Show new password"}
                    aria-pressed={showNewPassword}
                    onClick={() => setShowNewPassword((current) => !current)}
                  >
                    <Icon name={showNewPassword ? "eye-off" : "eye"} size={17} />
                  </button>
                </div>
              </label>

              <label>
                <span>Confirm new password</span>
                <div className="password-field">
                  <input
                    type={showConfirmPassword ? "text" : "password"}
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    placeholder="Enter the new password again"
                    required
                    minLength={8}
                    maxLength={256}
                  />
                  <button
                    className="password-toggle"
                    type="button"
                    aria-label={
                      showConfirmPassword
                        ? "Hide password confirmation"
                        : "Show password confirmation"
                    }
                    aria-pressed={showConfirmPassword}
                    onClick={() => setShowConfirmPassword((current) => !current)}
                  >
                    <Icon
                      name={showConfirmPassword ? "eye-off" : "eye"}
                      size={17}
                    />
                  </button>
                </div>
              </label>
            </>
          )}

          {isSignIn && (
            <button
              className="auth-forgot"
              type="button"
              onClick={openForgotPassword}
            >
              Forgot password?
            </button>
          )}

          {successMessage && (
            <div className="auth-notice" role="status">
              {successMessage}
            </div>
          )}

          {visibleError && (
            <div className="auth-error" role="alert">
              {visibleError}
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
            disabled={isSubmitting || isResending || !isApiBaseUrlConfigured}
          >
            {isSubmitting ? (
              <>
                <span className="auth-spinner" aria-hidden="true" />
                {isVerifyEmail || isResetPassword
                  ? "Verifying…"
                  : isForgotPassword
                    ? "Sending code…"
                    : isSignIn
                      ? "Signing in…"
                      : "Creating account…"}
              </>
            ) : (
              <>
                <Icon name="arrow" size={17} />
                {isVerifyEmail
                  ? "Verify email"
                  : isForgotPassword
                    ? "Send reset code"
                    : isResetPassword
                      ? "Set new password"
                      : isSignIn
                        ? "Sign in"
                        : "Create account"}
              </>
            )}
          </button>

          {isVerifyEmail && (
            <button
              className="secondary-action"
              type="button"
              disabled={isSubmitting || isResending}
              onClick={() => void handleResend()}
            >
              {isResending ? "Sending code…" : "Resend code"}
            </button>
          )}

          {(isForgotPassword || isResetPassword) && (
            <button
              className="secondary-action"
              type="button"
              disabled={isSubmitting || isResending}
              onClick={handleBackToSignIn}
            >
              Back to sign in
            </button>
          )}
        </form>

        <div className="auth-switch">
          {!isForgotPassword && !isResetPassword && (
            <>
              <span>
                {isVerifyEmail
                  ? "Entered the wrong email?"
                  : isSignIn
                    ? "New to NOVA?"
                    : "Already have a NOVA account?"}
              </span>
              <button type="button" onClick={switchMode}>
                {isVerifyEmail
                  ? "Back to sign in"
                  : isSignIn
                    ? "Create account"
                    : "Sign in"}
              </button>
            </>
          )}
        </div>
      </section>

      <p className="auth-footer">
        Secure session · Personal workspace · Voice-first experience
      </p>
    </main>
  )
}
