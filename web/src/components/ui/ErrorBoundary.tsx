import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "@/components/ui/icons";
import { Button } from "./Button";

type Props = {
  children: ReactNode;
  /** Reset the boundary when this value changes (e.g. the route path). */
  resetKey?: string;
};
type State = { error: Error | null };

/**
 * Catches render errors below it and shows a recoverable fallback instead of a
 * blank screen (the failure mode that white-screened the app before). Placed
 * around the routed content so the shell/nav survive a page-level crash.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("Render error caught by ErrorBoundary:", error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="mx-auto grid w-full max-w-md place-items-center py-16 text-center">
        <div className="surface-card w-full p-8">
          <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-full bg-[color-mix(in_srgb,var(--danger)_14%,transparent)] text-[var(--danger)]">
            <AlertTriangle className="h-6 w-6" />
          </div>
          <h2 className="font-[family-name:var(--font-display)] text-lg">Something went wrong on this page</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            The rest of the app is fine — reload this view to continue.
          </p>
          <div className="mt-5 flex justify-center">
            <Button onClick={() => this.setState({ error: null })}>
              <RefreshCw className="h-4 w-4" /> Reload this page
            </Button>
          </div>
        </div>
      </div>
    );
  }
}
