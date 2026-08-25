import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
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
import { CompareTray } from "./CompareTray";

/**
 * App shell — a slim glass top bar, the page content, and one floating glass
 * bottom nav (5 destinations, center Home FAB) on every viewport, plus the
 * draggable AssistiveTouch launcher. No sidebar.
 *
 * SCROLLING: the DOCUMENT scrolls, not an inner div. The previous shell was a
 * `max-h-[100dvh]` column with `overflow-y-auto` on <main>, which is what made
 * scrolling "feel off" on a phone:
 *   · the browser's own toolbar never collapses, because the page is exactly one
 *     viewport tall and nothing ever overflows it;
 *   · momentum and rubber-banding get emulated by the scroll container instead of
 *     coming from the platform compositor, so the deceleration curve is wrong;
 *   · `position: sticky` inside the box measures against the box, not the
 *     viewport, so sticky sub-headers drifted;
 *   · browser scroll restoration and `scrollIntoView` both target the wrong node.
 * Letting <html> scroll fixes all four at once. The costs are handled here and in
 * globals.css: scroll progress reads from `window`, anchor jumps get
 * `scroll-padding-top`, and the scroll lock moved to `html`.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { theme, toggle } = useTheme();
  const { user, signOut } = useAuth();
  const { canInstall, install } = useInstallPrompt();
  const { events } = useAgentStream();
  const { pathname, hash } = useLocation();

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

  /* Scroll progress (§10.5) + a "has scrolled" flag for the top bar. Both read
     the document scroller now. rAF-coalesced: scroll fires far more often than
     the compositor paints, and writing a custom property per event thrashes
     style recalc on low-end Android. */
  const progressRef = useRef<HTMLDivElement>(null);
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    let frame = 0;
    const read = () => {
      frame = 0;
      const doc = document.documentElement;
      const scrollable = doc.scrollHeight - doc.clientHeight;
      const top = doc.scrollTop;
      progressRef.current?.style.setProperty(
        "--p",
        String(scrollable > 4 ? Math.min(1, Math.max(0, top / scrollable)) : 0),
      );
      setScrolled(top > 6);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(read);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    read();
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  /* Land at the top of every new route. An inner scroller kept its own
     scrollTop across route changes, so navigating from halfway down a long
     results page dropped you halfway down the next one. `instant` is required:
     globals.css sets `scroll-behavior: smooth`, which would otherwise animate a
     navigation. A hash means the target is an anchor — leave it alone. */
  useEffect(() => {
    if (hash) return;
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [pathname, hash]);

  const initial = (user?.display_name || user?.email || "?").slice(0, 1).toUpperCase();

  return (
    <div className="min-h-[100dvh] bg-[var(--bg)] text-[var(--text)]">
      <div ref={progressRef} className="scroll-progress" aria-hidden />

      {/* Slim glass top bar. Height includes the safe-area inset so the glass
          paints up through the notch rather than starting below it. */}
      <header
        className={cn(
          "glass sticky top-0 z-40 flex items-center justify-between px-4 md:px-6",
          "border-x-0 border-t-0 transition-[border-color,box-shadow] duration-[var(--dur)]",
          scrolled
            ? "border-b-[color-mix(in_srgb,var(--text)_10%,transparent)] shadow-[0_1px_12px_rgba(11,16,32,0.06)]"
            : "border-b-transparent shadow-none",
        )}
        style={{
          height: "calc(var(--top-bar) + var(--safe-top))",
          paddingTop: "var(--safe-top)",
        }}
      >
        <Link
          to="/"
          className="pressable flex items-center gap-2 font-[family-name:var(--font-display)] text-lg font-semibold tracking-tight"
        >
          <span
            aria-hidden
            className="h-2 w-2 rounded-full bg-[var(--brand-500)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--brand-400)_22%,transparent)]"
          />
          Journava
        </Link>
        <div className="flex items-center gap-0.5">
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
            className="pressable ml-1 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[color-mix(in_srgb,var(--brand-400)_18%,transparent)] text-xs font-semibold text-[var(--brand-500)] ring-1 ring-[color-mix(in_srgb,var(--brand-500)_18%,transparent)]"
          >
            {initial}
          </Link>
        </div>
      </header>

      {/* Content. Bottom padding is its own utility (not a combined `p-*`) so a
          breakpoint variant can never quietly override the nav clearance and let
          the floating nav cover the last card. */}
      <main className="relative min-w-0 px-4 pt-5 md:px-6 md:pt-7" style={{ paddingBottom: "var(--nav-clearance)" }}>
        {children}
      </main>

      <BottomNav />
      <CompareTray />
      <AssistiveTouch />
    </div>
  );
}
