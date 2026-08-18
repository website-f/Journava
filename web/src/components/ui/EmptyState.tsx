import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type EmptyStateProps = {
  icon?: ReactNode;
  title: string;
  description?: string;
  /** A call-to-action button (e.g. "Create your first trip"). */
  action?: ReactNode;
  className?: string;
};

/**
 * Every content area that can be empty has a purposeful empty-state
 * with illustration + single action (spec §10.6 addendum).
 */
export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center py-16 px-6",
        className,
      )}
    >
      {icon && <div className="mb-4 text-[var(--muted)]">{icon}</div>}
      <h3 className="font-[family-name:var(--font-display)] text-lg">{title}</h3>
      {description && (
        <p className="mt-1 text-sm text-[var(--muted)] max-w-xs">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
