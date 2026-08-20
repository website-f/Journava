import { NavLink, useLocation } from "react-router-dom";
import { Compass, Briefcase, Bot, User, Home, type IconType } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

/**
 * Floating glass bottom nav — the single primary navigation on every viewport
 * (spec revamp). Five destinations, with a raised center Home FAB; the other
 * four (Research · Trip | Agents · Account) flank it. Settings-shaped pages are
 * folded into the Account hub and past runs into Trip, so this stays at five.
 */

type Item = { to: string; label: string; icon: IconType };

const LEFT: Item[] = [
  { to: "/research", label: "Research", icon: Compass },
  { to: "/trip", label: "Trip", icon: Briefcase },
];
const RIGHT: Item[] = [
  { to: "/agents", label: "Agents", icon: Bot },
  { to: "/account", label: "Account", icon: User },
];

function NavItem({ to, label, icon: Icon }: Item) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "flex w-14 flex-col items-center justify-center gap-0.5 rounded-[var(--r-md)] py-1.5",
          "text-[0.6rem] font-medium transition-colors",
          isActive ? "text-[var(--brand-500)]" : "text-[var(--muted)] hover:text-[var(--text)]",
        )
      }
    >
      <Icon className="h-[22px] w-[22px]" />
      <span>{label}</span>
    </NavLink>
  );
}

export function BottomNav() {
  const { pathname } = useLocation();
  const homeActive = pathname === "/";

  return (
    <div
      className="fixed left-1/2 z-50 -translate-x-1/2"
      style={{ bottom: "calc(env(safe-area-inset-bottom) + 0.85rem)" }}
    >
      <nav className="glass relative flex max-w-[calc(100vw-1rem)] items-end gap-1 rounded-[var(--r-pill)] px-3 py-2 shadow-[var(--shadow-2)]">
        {LEFT.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}
        <div className="w-14 shrink-0" aria-hidden />
        {RIGHT.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}

        {/* Raised center Home FAB */}
        <NavLink
          to="/"
          aria-label="Home"
          className="absolute -top-6 left-1/2 -translate-x-1/2"
        >
          <span
            className={cn(
              "grid h-14 w-14 place-items-center rounded-full text-white shadow-[var(--shadow-2)]",
              "border-2 border-[var(--bg)] transition-transform active:scale-95",
              "bg-[var(--brand-500)]",
              homeActive && "ring-2 ring-[var(--accent)] ring-offset-2 ring-offset-[var(--bg)]",
            )}
          >
            <Home className="h-6 w-6" />
          </span>
        </NavLink>
      </nav>
    </div>
  );
}
