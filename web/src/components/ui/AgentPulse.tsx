import { cn } from "@/lib/cn";

/**
 * Animated brand icon used in the LoadingOverlay and Agent Control Center.
 * Shows a pulsing ring effect (keyframe in globals.css).
 */
export function AgentPulse({ className }: { className?: string }) {
  return (
    <span className={cn("relative inline-flex items-center justify-center", className)}>
      {/* Outer pulse ring */}
      <span
        className="absolute inset-0 rounded-full bg-[var(--brand-400)] opacity-30"
        style={{ animation: "journava-pulse-ring 2s ease-out infinite" }}
      />
      {/* Core circle */}
      <span className="relative h-[60%] w-[60%] rounded-full bg-[var(--brand-500)] shadow-[0_0_16px_var(--brand-400)]" />
    </span>
  );
}
