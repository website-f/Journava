import { type ReactNode, useEffect, useRef } from "react";
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
} from "lucide-react";
import { cn } from "@/lib/cn";
import { useTheme } from "@/lib/theme";
import { useIsDesktop, useIsMobile } from "@/hooks/useMediaQuery";
import { useInstallPrompt } from "@/hooks/useInstallPrompt";
import { Button } from "@/components/ui";
import { useAgentStream } from "@/hooks/useAgentStream";

const LINKS = [
  { to: "/", label: "Command", icon: Home },
  { to: "/research", label: "Research", icon: Search },
  { to: "/trip", label: "My Trip", icon: Briefcase },
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/engine", label: "Engine", icon: Cpu },
  { to: "/profile", label: "Profile", icon: User },
] as const;

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

  return (
    <div
      className={cn(
        "min-h-[100dvh] bg-[var(--bg)] text-[var(--text)]",
        isDesktop
          ? "grid grid-cols-[14rem_1fr] grid-rows-[1fr]"
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
            {LINKS.map(({ to, label, icon: Icon }) => (
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
          <div className="mt-auto flex flex-col gap-1">
            {canInstall && (
              <Button variant="ghost" size="sm" onClick={install} className="text-xs">
                <Download className="h-4 w-4" /> Install App
              </Button>
            )}
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
          <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
            {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </Button>
        </header>
      )}

      {/* --- Main content area --- */}
      <main className="flex-1 overflow-y-auto p-4 md:p-6 min-w-0">
        {children}
      </main>

      {/* --- Bottom tab bar (mobile) --- */}
      {isMobile && (
        <nav className="sticky bottom-0 z-40 grid grid-cols-6 border-t border-[var(--border)] bg-[var(--surface)]/90 backdrop-blur-sm pb-[env(safe-area-inset-bottom)]">
          {LINKS.map(({ to, label, icon: Icon }) => {
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
        </nav>
      )}
    </div>
  );
}
