import { Component, type ErrorInfo, type ReactNode } from 'react'

/** Shows the error and a reload button instead of a blank/black page when a component throws. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('UI crashed:', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <div className="text-lg font-semibold">Something broke in the UI</div>
        <pre className="max-w-xl overflow-auto rounded-lg border border-line bg-surface p-3 text-left text-xs text-muted">{this.state.error.message}</pre>
        <div className="flex gap-2">
          <button className="btn-pink px-4 py-2" onClick={() => this.setState({ error: null })}>Try again</button>
          <button className="rounded-lg border border-line px-4 py-2" onClick={() => location.reload()}>Reload</button>
        </div>
      </div>
    )
  }
}
