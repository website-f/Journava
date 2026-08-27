import { useEffect, useRef, useState } from "react";
import { Calendar as CalendarIcon, X } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { Calendar, type DateRange } from "./Calendar";

/**
 * A date / date-range field that opens the app's own {@link Calendar} in a
 * floating panel — replaces the native `<input type=date>` so the picker looks
 * and behaves the same on every platform.
 */

function fmt(iso?: string): string | null {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(y, (m || 1) - 1, d || 1);
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function label(value: DateRange, mode: "single" | "range", placeholder: string): string {
  const start = fmt(value.start);
  if (!start) return placeholder;
  if (mode === "single") return start;
  const end = fmt(value.end);
  return end ? `${start} – ${end}` : `${start} – …`;
}

export function DateRangePicker({
  value,
  onChange,
  mode = "range",
  placeholder = "Add dates",
  min,
  className,
  autoOpen = false,
  inline = false,
}: {
  value: DateRange;
  onChange: (next: DateRange) => void;
  mode?: "single" | "range";
  placeholder?: string;
  min?: string;
  className?: string;
  /** Open the panel on mount — handy inside a "when?" prompt. */
  autoOpen?: boolean;
  /** Render the calendar in-flow (not an absolute popover) so it can't overflow
   *  a scrollable container like a dialog — the container scrolls to reveal it. */
  inline?: boolean;
}) {
  const [open, setOpen] = useState(autoOpen);
  const wrap = useRef<HTMLDivElement>(null);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const hasValue = Boolean(value.start);

  // Inline mode (e.g. the "when?" clarify step): show the calendar directly and
  // ALWAYS visible — no toggle field and, crucially, no "Done" button. Hiding it
  // behind a field + a Done that only collapsed the panel was read as a freeze
  // (nothing happened; the real submit is the parent's own button). Picks flow
  // straight to `onChange`; the parent's Continue button commits.
  if (inline) {
    return (
      <div ref={wrap} className={cn("w-full", className)}>
        <div className="rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--elevated)] p-3">
          <div className="flex justify-center">
            <Calendar mode={mode} value={value} onChange={onChange} min={min} />
          </div>
          <div className="mt-2 flex items-center justify-between border-t border-[var(--border)] pt-2">
            <span className={cn("text-xs font-medium", !hasValue && "text-[var(--muted)]")}>
              {label(value, mode, hasValue ? placeholder : "Tap a start and end date")}
            </span>
            {hasValue && (
              <button
                type="button"
                onClick={() => onChange({})}
                className="text-xs text-[var(--muted)] hover:text-[var(--text)]"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div ref={wrap} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="input-field flex w-full items-center gap-2 text-left"
      >
        <CalendarIcon className="h-4 w-4 shrink-0 text-[var(--brand-500)]" />
        <span className={cn("min-w-0 flex-1 truncate", !hasValue && "text-[var(--muted)]")}>
          {label(value, mode, placeholder)}
        </span>
        {hasValue && (
          <span
            role="button"
            tabIndex={0}
            aria-label="Clear dates"
            onClick={(e) => {
              e.stopPropagation();
              onChange({});
            }}
            className="grid h-5 w-5 shrink-0 place-items-center rounded-full hover:bg-[color-mix(in_srgb,var(--muted)_20%,transparent)]"
          >
            <X className="h-3 w-3" />
          </span>
        )}
      </button>

      {open && (
        <div
          className={cn(
            "mt-2 rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--elevated)] p-3 shadow-[var(--shadow-2)]",
            inline ? "w-full" : "absolute z-[90]",
          )}
        >
          <Calendar mode={mode} value={value} onChange={onChange} min={min} />
          <div className="mt-2 flex items-center justify-between border-t border-[var(--border)] pt-2">
            <button
              type="button"
              onClick={() => onChange({})}
              className="text-xs text-[var(--muted)] hover:text-[var(--text)]"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-[var(--r-pill)] bg-[var(--brand-500)] px-3 py-1 text-xs font-medium text-white"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
