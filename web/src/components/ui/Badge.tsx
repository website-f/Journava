/**
 * Badge — small inline status / scope indicator (Aurora tokens).
 */

import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

type BadgeVariant = "default" | "success" | "warning" | "danger" | "info" | "brand";

const VARIANT_STYLES: Record<BadgeVariant, string> = {
  default: "bg-[color-mix(in_srgb,var(--muted)_14%,transparent)] text-[var(--muted)]",
  success: "bg-[color-mix(in_srgb,var(--success)_14%,transparent)] text-[var(--success)]",
  warning: "bg-[color-mix(in_srgb,var(--warning)_14%,transparent)] text-[var(--warning)]",
  danger: "bg-[color-mix(in_srgb,var(--danger)_14%,transparent)] text-[var(--danger)]",
  info: "bg-[color-mix(in_srgb,var(--info)_14%,transparent)] text-[var(--info)]",
  brand: "bg-[color-mix(in_srgb,var(--brand-500)_14%,transparent)] text-[var(--brand-500)]",
};

interface BadgeProps {
  variant?: BadgeVariant;
  className?: string;
  /**
   * Native tooltip. A badge is often an abbreviation ("from .env", "sandbox"),
   * and the long form has to live somewhere the reader can reach.
   */
  title?: string;
  children: ReactNode;
}

export function Badge({
  variant = "default",
  className,
  title,
  children,
}: BadgeProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-[var(--r-pill)] px-2 py-0.5",
        "text-[0.65rem] font-medium uppercase tracking-wide whitespace-nowrap",
        VARIANT_STYLES[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}
