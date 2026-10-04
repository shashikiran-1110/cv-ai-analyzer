import { House, RefreshCw, TriangleAlert } from "lucide-react";
import { Component, type ReactNode } from "react";

/** A crash in one page shows a recovery card instead of a blank app (the shell stays usable). */
export class ErrorBoundary extends Component<{ children: ReactNode; onClearSession: () => void }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) { return { error }; }

  componentDidCatch(error: Error) { console.warn("page error:", error.message); }

  render() {
    const e = this.state.error;
    if (!e) return this.props.children;
    return (
      <section className="card empty-state" role="alert">
        <TriangleAlert aria-hidden="true" />
        <h2>This page hit a problem</h2>
        <p className="muted">{e.message || "Something went wrong while showing this page."} Your data is safe; try again, or start fresh.</p>
        <div className="actions" style={{ justifyContent: "center" }}>
          <button className="btn primary" onClick={() => this.setState({ error: null })}><RefreshCw aria-hidden="true" />Try again</button>
          <a className="btn" href="/"><House aria-hidden="true" />New search</a>
          <button className="btn ghost" onClick={this.props.onClearSession}>Clear session</button>
        </div>
      </section>
    );
  }
}
