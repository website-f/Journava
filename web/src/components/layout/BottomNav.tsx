import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { Compass, Briefcase, Bot, User, Home, type IconType } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

/**
 * Floating glass bottom nav — the single primary navigation on every viewport.
 * Five destinations, with a raised center Home FAB; the other four
 * (Research · Trip | Agents · Account) flank it. Settings-shaped pages are folded
 * into the Account hub and past runs into Trip, so this stays at five.
 *
 * Two details do most of the "native" work:
 *  · the active icon switches to Phosphor's `fill` weight, which is exactly what
 *    an iOS tab bar does — a colour change alone reads as a web link;
 *  · a single shared `layoutId` pill slides between items instead of each item
 *    fading its own background in and out.
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
    <NavLink to={to} className="group relative w-[3.75rem] shrink-0" aria-label={label}>
      {({ isActive }) => (
        <>
          {isActive && (
            <motion.span
              layoutId="nav-pill"
              aria-hidden
              className="absolute inset-0 rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)]"
              transition={{ type: "spring", stiffness: 480, damping: 34 }}
            />
          )}
          <span
            className={cn(
              "relative flex flex-col items-center justify-center gap-[3px] py-1.5",
              "text-[0.6rem] font-semibold tracking-[0.01em] transition-[color,transform] duration-[var(--dur)]",
              "group-active:scale-90",
              isActive
                ? "text-[var(--brand-500)]"
                : "text-[var(--muted)] group-hover:text-[var(--text)]",
            )}
          >
            <Icon className="h-[22px] w-[22px]" weight={isActive ? "fill" : "regular"} />
            {label}
          </span>
        </>
      )}
    </NavLink>
  );
}

export function BottomNav() {
  const { pathname } = useLocation();
  const homeActive = pathname === "/";

  return (
    <div
      className="fixed left-1/2 z-50 -translate-x-1/2"
      // The nav floats clear of the home-indicator strip rather than sitting on it.
      style={{ bottom: "calc(var(--safe-bottom) + 0.85rem)" }}
    >
      <nav
        aria-label="Primary"
        className="glass-strong relative flex max-w-[calc(100vw-1rem)] items-end gap-0.5 rounded-[var(--r-pill)] px-2.5 py-1.5 shadow-[var(--shadow-3)]"
      >
        {LEFT.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}
        {/* Reserved slot under the raised FAB. */}
        <div className="w-[3.75rem] shrink-0" aria-hidden />
        {RIGHT.map((item) => (
          <NavItem key={item.to} {...item} />
        ))}

        {/* Raised center Home FAB */}
        <NavLink to="/" aria-label="Home" className="absolute -top-[1.4rem] left-1/2 -translate-x-1/2">
          <span
            className={cn(
              "grid h-[3.35rem] w-[3.35rem] place-items-center rounded-full text-white",
              "bg-[var(--brand-500)] shadow-[var(--shadow-3)]",
              // A ring in the page background colour punches the FAB visually out
              // of the glass bar instead of letting it merge into it.
              "ring-[3px] ring-[var(--bg)]",
              "transition-transform duration-[var(--dur)] ease-[var(--ease-spring)] active:scale-[0.92]",
              homeActive && "shadow-[0_0_0_2px_var(--accent),var(--shadow-3)]",
            )}
          >
            <Home className="h-[26px] w-[26px]" weight={homeActive ? "fill" : "regular"} />
          </span>
        </NavLink>
      </nav>
    </div>
  );
}
