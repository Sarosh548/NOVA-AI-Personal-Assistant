import { Component, type ErrorInfo, type ReactNode } from "react"

type AppErrorBoundaryProps = {
  resetKey: string
  children: ReactNode
}

type AppErrorBoundaryState = {
  hasError: boolean
}

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = {
    hasError: false,
  }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("NOVA application error", error, info)
  }

  componentDidUpdate(previousProps: AppErrorBoundaryProps) {
    if (
      previousProps.resetKey !== this.props.resetKey &&
      this.state.hasError
    ) {
      this.setState({ hasError: false })
    }
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children
    }

    return (
      <div className="app-error-shell" role="alert">
        <div className="app-error-card">
          <div className="brand-mark">
            <span className="loading-pulse" />
          </div>
          <div className="section-kicker">NOVA RECOVERY</div>
          <h1>That workspace hit an unexpected error.</h1>
          <p>
            The rest of NOVA is still available. Reload the application to
            restore a clean session.
          </p>
          <button
            className="primary-action"
            type="button"
            onClick={() => window.location.reload()}
          >
            Reload NOVA
          </button>
        </div>
      </div>
    )
  }
}
