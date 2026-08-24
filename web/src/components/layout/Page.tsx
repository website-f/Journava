import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Page-level layout primitives.
 *
 * Every feature page had been hand-rolling `mx-auto w-full max-w-5xl`, its own
 * heading sizes and its own horizontal card rail, and they had all drifted apart —
 * six different title sizes, four different rail card widths, and no two pages
 * agreeing on where the content column starts. These are the shared pieces, so a
 * revamp changes one file instead of fourteen.
 *
 * AppShell owns the page gutters (px-4 / md:px-6) and the bottom nav clearance;
 * nothing here should re-add either.
 */

type Width = "sm" | "md" | "lg" | "xl" | "full";

const WIDTHS: Record<Width, string> = {
  sm: "max-w-2xl", // single-column forms (Profile, Integrations)
  md: "max-w-4xl", // settings / lists
  lg: "max-w-5xl", // default reading column (Home, Results, Trip detail)
  xl: "max-w-6xl", // dense dashboards (Agents, Research, Trip gallery)
  full: "",
};

export function Page({
  children,
  width = "lg",
  className,
}: {
  children: ReactNode;
  width?: Width;
  className?: string;
}) {
  return <div className={cn("mx-auto w-full", WIDTHS[width], className)}>{children}</div>;
}

/**
 * The big title block at the top of a page. Deliberately larger and tighter than
 * a web-page h1: oversized display type with negative tracking is most of what
 * separates a native app header from a generic dashboard heading.
 */
export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
  className,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-6 flex flex-wrap items-end justify-between gap-x-4 gap-y-3", className)}>
      <div className="min-w-0 flex-1">
        {eyebrow && (
          <p className="mb-1.5 text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">
            {eyebrow}
          </p>
        )}
        <h1 className="font-[family-name:var(--font-display)] text-[1.75rem] font-bold leading-[1.1] tracking-[-0.025em] sm:text-[2.15rem]">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-2 max-w-[46ch] text-sm leading-relaxed text-[var(--muted)]">{subtitle}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}

/**
 * Section heading inside a page. `count` renders as a muted tally next to the
 * label (so "Stays 12" reads as one unit), `action` sits flush right.
 */
export function SectionHeader({
  icon,
  title,
  count,
  hint,
  action,
  className,
}: {
  icon?: ReactNode;
  title: ReactNode;
  count?: number;
  hint?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-3 flex items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 font-[family-name:var(--font-display)] text-[1.0625rem] font-semibold tracking-[-0.01em]">
          {icon}
          <span className="truncate">{title}</span>
          {count != null && (
            <span className="shrink-0 rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--text)_6%,transparent)] px-2 py-0.5 text-[0.7rem] font-semibold tabular-nums text-[var(--muted)]">
              {count}
            </span>
          )}
        </h2>
        {hint && <p className="mt-1 text-xs text-[var(--muted)]">{hint}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

interface RailProps {
  children: ReactNode;
  /** Card width while it IS a rail (mobile). Ignored once it becomes a grid. */
  card?: string;
  /** Grid columns at md / lg once the rail degrades to a grid. */
  cols?: number;
  colsLg?: number;
  /**
   * Gutter this rail bleeds into, e.g. `"1rem"` for the page gutter or `"0px"`
   * for a rail nested in an already-padded card. Wins over `flush`/`locked`,
   * which only set defaults.
   */
  pad?: string;
  /** Nested inside an already-padded card: don't bleed into the page gutter. */
  flush?: boolean;
  /** Stay a rail at every width (chip strips, filter rows, carousels). */
  locked?: boolean;
  className?: string;
  "aria-label"?: string;
}

/**
 * Horizontal card rail on phones, plain grid from `md` up.
 *
 * The alignment and whitespace behaviour lives in the `.rail` class in
 * globals.css — in particular the `scroll-padding-inline` that stops a
 * `snap-start` card from parking one gutter to the left of the heading above it,
 * which is what made these rails feel misaligned on every swipe.
 */
export function Rail({
  children,
  card,
  cols,
  colsLg,
  pad,
  flush,
  locked,
  className,
  "aria-label": ariaLabel,
}: RailProps) {
  const vars: Record<string, string> = {};
  if (card) vars["--rail-card"] = card;
  if (cols) vars["--rail-cols"] = String(cols);
  if (colsLg) vars["--rail-cols-lg"] = String(colsLg);
  if (pad) vars["--rail-pad"] = pad;

  return (
    <div
      aria-label={ariaLabel}
      className={cn("rail", flush && "rail-flush", locked && "rail-locked", className)}
      style={vars as CSSProperties}
    >
      {children}
    </div>
  );
}
