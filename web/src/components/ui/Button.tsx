import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Slot } from "@radix-ui/react-slot";
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
  const Comp = asChild ? Slot : "button";

  return (
    <Comp
      {...props}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
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
      )}
    >
      {loading && <Spinner className="h-4 w-4" />}
      <span className={cn("inline-flex items-center gap-2", loading && "opacity-90")}>
        {children}
      </span>
    </Comp>
  );
}
