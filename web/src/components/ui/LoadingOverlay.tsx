import { AnimatePresence, motion } from "framer-motion";
import { cn } from "@/lib/cn";
import { useScrollLock } from "@/hooks/useScrollLock";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { AgentPulse } from "./AgentPulse";

type OverlayProps = {
  open: boolean;
  title?: string;
  sub?: string;
};

const AGENT_NAMES = ["Chief", "Flight", "Hotel", "Research", "Weather", "Budget", "Itinerary", "Memory"];

/**
 * Full-screen loading overlay for heavy operations — planning a trip, running
 * the disruption recovery (spec §10.6). Locks scroll, blurs backdrop, traps
 * focus, shows the agent pulse animation with staggered agent names.
 */
export function LoadingOverlay({ open, title, sub }: OverlayProps) {
  useScrollLock(open);
  const trapRef = useFocusTrap<HTMLDivElement>(open);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          role="dialog"
          aria-modal="true"
          aria-live="assertive"
          className={cn(
            "fixed inset-0 z-[80] grid place-items-center",
            "bg-black/40 backdrop-blur-md p-6",
          )}
        >
          <motion.div
            ref={trapRef}
            tabIndex={-1}
            initial={{ y: 12, scale: 0.98 }}
            animate={{ y: 0, scale: 1 }}
            exit={{ y: 12, scale: 0.98, opacity: 0 }}
            className={cn(
              "w-full max-w-md rounded-[var(--r-lg)] bg-[var(--elevated)]",
              "border border-[var(--border)] shadow-[var(--shadow-2)] p-8 text-center",
              "outline-none",
            )}
          >
            <AgentPulse className="mx-auto h-16 w-16" />
            <h3 className="mt-4 font-[family-name:var(--font-display)] text-lg">
              {title ?? "Journava is working…"}
            </h3>
            {sub && <p className="mt-1 text-sm text-[var(--muted)]">{sub}</p>}

            {/* Staggered agent names appearing one by one */}
            <div className="mt-5 flex flex-wrap justify-center gap-1.5">
              {AGENT_NAMES.map((name, i) => (
                <motion.span
                  key={name}
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: 0.3 + i * 0.15, duration: 0.3 }}
                  className={cn(
                    "inline-flex items-center rounded-[var(--r-pill)] px-2 py-0.5",
                    "text-[0.65rem] font-medium",
                    "bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)]",
                    "text-[var(--brand-500)]",
                  )}
                >
                  {name}
                </motion.span>
              ))}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
