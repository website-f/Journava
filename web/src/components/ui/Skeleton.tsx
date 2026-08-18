import { cn } from "@/lib/cn";

type SkeletonProps = { className?: string };

/**
 * Shimmer skeleton block — preferred over spinners for content areas (spec §10.6).
 * Apply width/height via className. Follows reduced-motion.
 */
export function Skeleton({ className }: SkeletonProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "block rounded-[var(--r-sm)] bg-[var(--border)]",
        "relative isolate overflow-hidden",
        className,
      )}
    >
      <span
        className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/20 to-transparent"
        style={{ animation: "journava-shimmer 1.5s infinite" }}
      />
    </span>
  );
}
