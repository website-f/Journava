import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { toast } from "sonner";
import {
  Home,
  Search,
  Briefcase,
  Bot,
  User,
  Moon,
  Sun,
  Cpu,
  Download,
  History as HistoryIcon,
  KeyRound,
  LogOut,
  Menu,
} from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { useTheme } from "@/lib/theme";
import { useAuth } from "@/providers/AuthProvider";
import { useIsDesktop, useIsMobile } from "@/hooks/useMediaQuery";
import { useInstallPrompt } from "@/hooks/useInstallPrompt";
import { Button } from "@/components/ui";
import { useAgentStream } from "@/hooks/useAgentStream";
import { AgentStreamColumn, AgentStreamDrawer } from "./AgentStreamPanel";
import { MobileMoreSheet } from "./MobileMoreSheet";

/**
 * Primary navigation. `mobile: false` keeps a link out of the bottom tab bar —
 * eight tabs on a phone is a row of unreadable slivers, so the settings-shaped
 * surfaces stay desktop-side while remaining reachable by URL.
 */
const LINKS = [
  { to: "/", label: "Command", icon: Home, mobile: true },
  { to: "/research", label: "Research", icon: Search, mobile: true },
  { to: "/trip", label: "My Trip", icon: Briefcase, mobile: true },
  { to: "/history", label: "History", icon: HistoryIcon, mobile: true },
  { to: "/agents", label: "Agents", icon: Bot, mobile: true },
  { to: "/vault", label: "API Vault", icon: KeyRound, mobile: false },
  { to: "/engine", label: "Engine", icon: Cpu, mobile: false },
  { to: "/profile", label: "Profile", icon: User, mobile: false },
] as const;

const MOBILE_LINKS = LINKS.filter((link) => link.mobile);

//: Surfaces only a platform admin may open — hidden from the nav for everyone
//: else (and gated in the router too).
const ADMIN_ONLY = new Set<string>(["/engine", "/vault"]);

/**
 * Responsive shell — spec §10.7.
 * Desktop: sidebar + main + optional right panel.
 * Mobile: top bar + main + bottom tab bar.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const isDesktop = useIsDesktop();
  const isMobile = useIsMobile();
  const { theme, toggle } = useTheme();
  const location = useLocation();
  const { events } = useAgentStream();
  const { canInstall, install } = useInstallPrompt();
  const { user, isPlatformAdmin, signOut } = useAuth();
  const [moreOpen, setMoreOpen] = useState(false);

  const visibleLinks = LINKS.filter(
    (link) => !ADMIN_ONLY.has(link.to) || isPlatformAdmin,
  );
  // Everything not in the mobile bottom bar (Profile always; Engine/Vault for
  // admins) lives behind the mobile "More" sheet so it's reachable on a phone.
  const secondaryLinks = visibleLinks.filter((link) => !link.mobile);

  // Global toast when any agent emits an "error" status
  const lastErrorId = useRef<string | null>(null);
  useEffect(() => {
    const latest = events[0];
    if (!latest) return;
    if (latest.status === "error" && latest.id !== lastErrorId.current) {
      lastErrorId.current = latest.id;
      toast.error(`${latest.agent}: ${latest.message}`);
    }
  }, [events]);

  // Scroll progress bar (spec §10.5)
  const mainRef = useRef<HTMLElement>(null);
  const updateScrollProgress = useCallback(() => {
    const el = mainRef.current;
    if (!el) return;
    const scrolled = el.scrollTop;
    const scrollable = el.scrollHeight - el.clientHeight;
    const p = scrollable > 0 ? scrolled / scrollable : 0;
    el.style.setProperty("--p", String(p));
  }, []);

  useEffect(() => {
    const el = mainRef.current;
    if (!el) return;
    el.addEventListener("scroll", updateScrollProgress, { passive: true });
    return () => el.removeEventListener("scroll", updateScrollProgress);
  }, [updateScrollProgress]);

  return (
    <div
      className={cn(
        "min-h-[100dvh] max-h-[100dvh] bg-[var(--bg)] text-[var(--text)]",
        // §10.7: sidebar · main · agent stream on desktop. The stream column
        // sizes itself (collapsed or expanded), hence `auto` rather than a fixed
        // track — the main column keeps `1fr` and never overflows.
        isDesktop
          ? "grid grid-cols-[14rem_1fr_auto] grid-rows-[1fr]"
          : "flex flex-col",
      )}
    >
      {/* --- Sidebar (desktop) / Top bar (mobile) --- */}
      {isDesktop ? (
        <aside className="flex flex-col border-r border-[var(--border)] bg-[var(--surface)] p-4 gap-1">
          <h1 className="font-[family-name:var(--font-display)] text-xl px-3 py-2 mb-4 tracking-tight">
            Journava
          </h1>
          <nav className="flex flex-col gap-1">
            {visibleLinks.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 px-3 py-2.5 rounded-[var(--r-md)]",
                    "text-sm font-medium transition-colors duration-[var(--dur)]",
                    isActive
                      ? "bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)] text-[var(--brand-500)]"
                      : "text-[var(--muted)] hover:text-[var(--text)] hover:bg-[color-mix(in_srgb,var(--brand-400)_6%,transparent)]",
                  )
                }
              >
                <Icon className="h-[18px] w-[18px]" />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="mt-auto flex flex-col gap-2">
            {canInstall && (
              <Button variant="ghost" size="sm" onClick={install} className="text-xs">
                <Download className="h-4 w-4" /> Install App
              </Button>
            )}
            <div className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] p-2">
              <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[color-mix(in_srgb,var(--brand-400)_18%,transparent)] text-xs font-semibold text-[var(--brand-500)]">
                {(user?.display_name || user?.email || "?").slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">{user?.display_name ?? "Account"}</p>
                <p className="truncate text-[0.65rem] text-[var(--muted)]">{user?.email}</p>
              </div>
              <button
                onClick={() => signOut()}
                aria-label="Sign out"
                className="shrink-0 rounded-[var(--r-sm)] p-1.5 text-[var(--muted)] hover:text-[var(--danger)] hover:bg-[color-mix(in_srgb,var(--danger)_10%,transparent)]"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
            <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
              {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>
          </div>
        </aside>
      ) : (
        <header className="sticky top-0 z-40 flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface)]/80 backdrop-blur-sm px-4 h-14">
          <h1 className="font-[family-name:var(--font-display)] text-lg tracking-tight">
            Journava
          </h1>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
              {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>
            <Button variant="ghost" size="icon" onClick={() => signOut()} aria-label="Sign out">
              <LogOut className="h-5 w-5" />
            </Button>
          </div>
        </header>
      )}

      {/* --- Main content area --- */}
      <main
        ref={mainRef}
        className={cn(
          "flex-1 overflow-y-auto p-4 md:p-6 min-w-0 relative",
          // Room for the swipe-up stream tab so it never covers page content.
          !isDesktop && "pb-20",
        )}
      >
        <div className="scroll-progress" style={{ position: "sticky", top: 0, zIndex: 50 }} />
        {children}
      </main>

      {/* --- Agent stream: right column on desktop, swipe-up drawer on mobile --- */}
      {isDesktop ? <AgentStreamColumn /> : <AgentStreamDrawer />}

      {/* --- Bottom tab bar (mobile) --- */}
      {isMobile && (
        <nav
          className="sticky bottom-0 z-40 grid border-t border-[var(--border)] bg-[var(--surface)]/90 backdrop-blur-sm pb-[env(safe-area-inset-bottom)]"
          style={{
            gridTemplateColumns: `repeat(${MOBILE_LINKS.length + 1}, minmax(0, 1fr))`,
          }}
        >
          {MOBILE_LINKS.map(({ to, label, icon: Icon }) => {
            const active = location.pathname === to;
            return (
              <NavLink
                key={to}
                to={to}
                className={cn(
                  "flex flex-col items-center gap-0.5 py-2 text-[0.65rem] font-medium",
                  active ? "text-[var(--brand-500)]" : "text-[var(--muted)]",
                )}
              >
                <Icon className="h-5 w-5" />
                {label}
              </NavLink>
            );
          })}
          <button
            onClick={() => setMoreOpen(true)}
            className={cn(
              "flex flex-col items-center gap-0.5 py-2 text-[0.65rem] font-medium",
              secondaryLinks.some((l) => l.to === location.pathname)
                ? "text-[var(--brand-500)]"
                : "text-[var(--muted)]",
            )}
          >
            <Menu className="h-5 w-5" />
            More
          </button>
        </nav>
      )}

      <MobileMoreSheet open={moreOpen} onOpenChange={setMoreOpen} links={secondaryLinks} />
    </div>
  );
}
