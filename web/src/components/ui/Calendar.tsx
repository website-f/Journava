import { useMemo, useState } from "react";
import { ChevronDown } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

/**
 * A self-contained month calendar — the app's own date UI, so we never fall
 * back to the browser's native (and platform-inconsistent) `<input type=date>`.
 *
 * Works on ISO `YYYY-MM-DD` strings throughout to sidestep timezone drift, and
 * supports either a single date or a start→end range. No external deps.
 */

const WEEKDAYS = ["S", "M", "T", "W", "T", "F", "S"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export interface DateRange {
  start?: string;
  end?: string;
}

const pad = (n: number) => String(n).padStart(2, "0");
const toISO = (y: number, m: number, d: number) => `${y}-${pad(m + 1)}-${pad(d)}`;

/** Today as an ISO string, in the viewer's local timezone. */
function todayISO(): string {
  const now = new Date();
  return toISO(now.getFullYear(), now.getMonth(), now.getDate());
}

/** First month to show: the selection's start, else today. */
function initialView(sel: DateRange): { y: number; m: number } {
  const anchor = sel.start || todayISO();
  const [y, m] = anchor.split("-").map(Number);
  return { y, m: (m || 1) - 1 };
}

export function Calendar({
  mode = "range",
  value,
  onChange,
  min,
}: {
  mode?: "single" | "range";
  value: DateRange;
  onChange: (next: DateRange) => void;
  /** Earliest selectable day (ISO). Defaults to today — no planning the past. */
  min?: string;
}) {
  const floor = min ?? todayISO();
  const [view, setView] = useState(() => initialView(value));

  const grid = useMemo(() => {
    const first = new Date(view.y, view.m, 1);
    const lead = first.getDay(); // 0 = Sunday
    const daysInMonth = new Date(view.y, view.m + 1, 0).getDate();
    const cells: (string | null)[] = [];
    for (let i = 0; i < lead; i++) cells.push(null);
    for (let d = 1; d <= daysInMonth; d++) cells.push(toISO(view.y, view.m, d));
    return cells;
  }, [view]);

  const step = (delta: number) => {
    const next = new Date(view.y, view.m + delta, 1);
    setView({ y: next.getFullYear(), m: next.getMonth() });
  };

  const pick = (iso: string) => {
    if (iso < floor) return;
    if (mode === "single") {
      onChange({ start: iso, end: iso });
      return;
    }
    const { start, end } = value;
    // No start yet, or a full range already chosen → begin a new range.
    if (!start || (start && end)) {
      onChange({ start: iso, end: undefined });
    } else if (iso >= start) {
      onChange({ start, end: iso });
    } else {
      onChange({ start: iso, end: undefined }); // clicked earlier → restart
    }
  };

  const inRange = (iso: string) =>
    mode === "range" &&
    value.start &&
    value.end &&
    iso > value.start &&
    iso < value.end;

  return (
    <div className="w-[17rem] select-none">
      <div className="mb-2 flex items-center justify-between">
        <button
          type="button"
          onClick={() => step(-1)}
          aria-label="Previous month"
          className="grid h-7 w-7 place-items-center rounded-[var(--r-sm)] hover:bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)]"
        >
          <ChevronDown className="h-4 w-4 rotate-90" />
        </button>
        <span className="text-sm font-semibold">
          {MONTHS[view.m]} {view.y}
        </span>
        <button
          type="button"
          onClick={() => step(1)}
          aria-label="Next month"
          className="grid h-7 w-7 place-items-center rounded-[var(--r-sm)] hover:bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)]"
        >
          <ChevronDown className="h-4 w-4 -rotate-90" />
        </button>
      </div>

      <div className="mb-1 grid grid-cols-7 gap-0.5">
        {WEEKDAYS.map((w, i) => (
          <span key={i} className="text-center text-[0.6rem] font-medium uppercase text-[var(--muted)]">
            {w}
          </span>
        ))}
      </div>

      <div className="grid grid-cols-7 gap-0.5">
        {grid.map((iso, i) => {
          if (!iso) return <span key={i} />;
          const disabled = iso < floor;
          const isStart = iso === value.start;
          const isEnd = iso === value.end;
          const isToday = iso === todayISO();
          const edge = isStart || isEnd;
          return (
            <button
              key={i}
              type="button"
              disabled={disabled}
              onClick={() => pick(iso)}
              className={cn(
                "relative h-8 rounded-[var(--r-sm)] text-xs transition-colors",
                disabled && "cursor-not-allowed text-[var(--muted)] opacity-40",
                !disabled && !edge && !inRange(iso) && "hover:bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)]",
                inRange(iso) && "bg-[color-mix(in_srgb,var(--brand-400)_18%,transparent)]",
                edge && "bg-[var(--brand-500)] font-semibold text-white",
                isToday && !edge && "font-semibold text-[var(--brand-600)]",
              )}
            >
              {Number(iso.slice(8))}
            </button>
          );
        })}
      </div>
    </div>
  );
}
