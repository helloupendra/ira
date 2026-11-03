import { Component, type ReactNode } from "react";

// A page that failed to draw, most often a chunk the last deploy replaced: say so and offer a
// reload, rather than leave the console blank.
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" style={{ padding: 24 }}>
        <p>This page could not load. The console may have just been updated.</p>
        <button type="button" onClick={() => location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}

const RELOADED = "ira.reloaded-at";
const ONCE_IN = 60_000;

// The first time a chunk is gone after a deploy, reload once to get the new ones.
export function reloadOnStaleChunks(): void {
  window.addEventListener("vite:preloadError", (event) => {
    let last = 0;
    try {
      last = Number(sessionStorage.getItem(RELOADED) ?? 0);
      sessionStorage.setItem(RELOADED, String(Date.now()));
    } catch {
      return; // no way to tell a loop from a first time: the boundary offers the button
    }
    if (Date.now() - last < ONCE_IN) return;
    event.preventDefault();
    location.reload();
  });
}
