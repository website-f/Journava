import { type ReactNode, useId, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "./icons";
import { cn } from "@/lib/cn";

/**
 * A disclosure card: header row you tap, body that expands.
 *
 * Built on framer-motion rather than a `<details>` element or a new Radix
 * dependency. `<details>` cannot animate its own open/close, and an unanimated
 * jump is the single biggest tell that a section is a web accordion rather than
 * an app row — the height transition is the point, not decoration.
 *
 * Used to keep long result pages navigable: the advisory sections (money,
 * shopping, language, analytics…) are real content but nobody reads twelve of
 * them at once, so they arrive collapsed with their summary line visible.
 */
export function Collapsible({
  title,
  icon,
  meta,
  summary,
  defaultOpen = false,
  children,
  className,
}: {
  title: ReactNode;
  icon?: ReactNode;
  /** Small right-aligned annotation in the header (count, status, price…). */
  meta?: ReactNode;
  /** One line that stays visible while collapsed, so the row is still useful. */
  summary?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();

  return (
    <div className={cn("surface-card overflow-hidden", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={bodyId}
        className={cn(
          "flex w-full items-center gap-3 px-4 py-3.5 text-left",
          "transition-colors duration-[var(--dur)]",
          "hover:bg-[color-mix(in_srgb,var(--brand-400)_6%,transparent)]",
          "active:bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)]",
        )}
      >
        {icon && <span className="shrink-0 text-[var(--brand-500)]">{icon}</span>}
        <span className="min-w-0 flex-1">
          <span className="block truncate font-[family-name:var(--font-display)] text-[0.9375rem] font-semibold">
            {title}
          </span>
          {summary && !open && (
            <span className="mt-0.5 block truncate text-xs text-[var(--muted)]">{summary}</span>
          )}
        </span>
        {meta && <span className="shrink-0 text-xs text-[var(--muted)]">{meta}</span>}
        <ChevronDown
          aria-hidden
          className={cn(
            "h-4 w-4 shrink-0 text-[var(--muted)] transition-transform duration-[var(--dur)] ease-[var(--ease)]",
            open && "rotate-180",
          )}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={bodyId}
            key="body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
            // Overflow must be clipped for the height animation to read as a
            // reveal rather than content sliding over the row below it.
            className="overflow-hidden"
          >
            <div className="border-t border-[var(--border)] px-4 py-4">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
