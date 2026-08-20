import { type ReactNode, useCallback, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Moon, Sun, Download, LogOut } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { useTheme } from "@/lib/theme";
import { useAuth } from "@/providers/AuthProvider";
import { useInstallPrompt } from "@/hooks/useInstallPrompt";
import { Button } from "@/components/ui";
import { useAgentStream } from "@/hooks/useAgentStream";
import { BottomNav } from "./BottomNav";
import { AssistiveTouch } from "./AssistiveTouch";

/**
 * App shell (native-app revamp): a slim glass top bar, a scrollable content
 * area, and one floating glass bottom nav (5 destinations, center Home FAB) on
 * every viewport — plus a draggable AssistiveTouch launcher. No sidebar.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { theme, toggle } = useTheme();
  const { user, signOut } = useAuth();
  const { canInstall, install } = useInstallPrompt();
  const { events } = useAgentStream();

  // Global toast when any agent emits an "error" status.
  const lastErrorId = useRef<string | null>(null);
  useEffect(() => {
    const latest = events[0];
    if (!latest) return;
    if (latest.status === "error" && latest.id !== lastErrorId.current) {
      lastErrorId.current = latest.id;
      toast.error(`${latest.agent}: ${latest.message}`);
    }
  }, [events]);

  // Custom scroll-progress bar (§10.5).
  const mainRef = useRef<HTMLElement>(null);
  const updateScrollProgress = useCallback(() => {
    const el = mainRef.current;
    if (!el) return;
    const scrollable = el.scrollHeight - el.clientHeight;
    el.style.setProperty("--p", String(scrollable > 0 ? el.scrollTop / scrollable : 0));
  }, []);
  useEffect(() => {
    const el = mainRef.current;
    if (!el) return;
    el.addEventListener("scroll", updateScrollProgress, { passive: true });
    return () => el.removeEventListener("scroll", updateScrollProgress);
  }, [updateScrollProgress]);

  const initial = (user?.display_name || user?.email || "?").slice(0, 1).toUpperCase();

  return (
    <div className="flex min-h-[100dvh] max-h-[100dvh] flex-col bg-[var(--bg)] text-[var(--text)]">
      {/* Slim glass top bar */}
      <header className="glass sticky top-0 z-40 flex h-14 shrink-0 items-center justify-between px-4">
        <Link to="/" className="font-[family-name:var(--font-display)] text-lg tracking-tight">
          Journava
        </Link>
        <div className="flex items-center gap-1">
          {canInstall && (
            <Button variant="ghost" size="sm" onClick={install} className="text-xs">
              <Download className="h-4 w-4" /> Install
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
            {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </Button>
          <Button variant="ghost" size="icon" onClick={() => signOut()} aria-label="Sign out">
            <LogOut className="h-5 w-5" />
          </Button>
          <Link
            to="/account"
            aria-label="Account"
            className="ml-1 grid h-9 w-9 place-items-center rounded-full bg-[color-mix(in_srgb,var(--brand-400)_18%,transparent)] text-xs font-semibold text-[var(--brand-500)]"
          >
            {initial}
          </Link>
        </div>
      </header>

      {/* Content — extra bottom padding so the floating nav never covers it */}
      <main
        ref={mainRef}
        className={cn(
          "relative min-w-0 flex-1 overflow-y-auto",
          // Axis-split padding: a combined `p-*`/`md:p-*` also sets padding-bottom
          // and (at md) overrode the clearance below, letting the floating nav
          // cover content on desktop. Keep bottom padding on its own utility so
          // it always wins across breakpoints.
          "px-4 pt-4 md:px-6 md:pt-6",
          "pb-[9.5rem]",
        )}
      >
        <div className="scroll-progress" style={{ position: "sticky", top: 0, zIndex: 50 }} />
        {children}
      </main>

      <BottomNav />
      <AssistiveTouch />
    </div>
  );
}
