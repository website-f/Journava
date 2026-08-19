import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Slot, Slottable } from "@radix-ui/react-slot";
import { cn } from "@/lib/cn";
import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg" | "icon";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  /** Render as the single child element (e.g. a router <Link>). */
  asChild?: boolean;
  children?: ReactNode;
};

const VARIANTS: Record<Variant, string> = {
  primary: cn(
    "bg-[var(--brand-500)] text-white shadow-[var(--shadow-1)]",
    "hover:bg-[var(--brand-600)]",
  ),
  secondary: cn(
    "bg-[var(--surface)] text-[var(--text)] border border-[var(--border)]",
    "shadow-[var(--shadow-1)] hover:border-[var(--brand-400)]",
  ),
  ghost: cn(
    "bg-transparent text-[var(--text)]",
    "hover:bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)]",
  ),
  danger: cn(
    "bg-[var(--danger)] text-white shadow-[var(--shadow-1)]",
    "hover:brightness-95",
  ),
};

const SIZES: Record<Size, string> = {
  sm: "h-9 px-4 text-sm min-w-[5.5rem]",
  md: "h-11 px-5 min-w-[7rem]", // min-w reserves room so the spinner never shifts layout
  lg: "h-12 px-7 text-[1.0625rem] min-w-[8rem]",
  icon: "h-11 w-11 p-0 min-w-0",
};

/**
 * Every click shows loading + disabled state without layout shift (spec §10.2).
 * Pair with `useAsync` so async handlers toggle `loading` automatically.
 */
export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  asChild = false,
  className,
  children,
  ...props
}: ButtonProps) {
  const classes = cn(
    "inline-flex items-center justify-center gap-2 rounded-[var(--r-pill)]",
    "font-medium select-none whitespace-nowrap",
    "transition-[transform,background,box-shadow,border-color]",
    "duration-[var(--dur)] ease-[var(--ease)]",
    "active:scale-[.98]",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
    "disabled:opacity-60 disabled:pointer-events-none",
    VARIANTS[variant],
    SIZES[size],
    className,
  );

  // asChild renders the caller's element (a router <Link>, an <a>) instead of a
  // <button>, and Radix `Slot` merges props onto exactly ONE element child.
  //
  // Rendering the spinner as a plain sibling made that two children and tripped
  // `Children.only` — "Slot failed to slot onto its children". `Slottable` is the
  // supported way out: it marks which child is the element to merge onto, so the
  // spinner can still render *inside* it. That keeps the loading state working on
  // link-shaped buttons and makes the failure mode structurally impossible rather
  // than a rule every call site has to remember.
  if (asChild) {
    return (
      <Slot {...props} className={classes} aria-busy={loading || undefined}>
        {loading && <Spinner className="h-4 w-4" />}
        <Slottable>{children}</Slottable>
      </Slot>
    );
  }

  return (
    <button
      {...props}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={classes}
    >
      {loading && <Spinner className="h-4 w-4" />}
      <span className={cn("inline-flex items-center gap-2", loading && "opacity-90")}>
        {children}
      </span>
    </button>
  );
}
