import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

/**
 * A number input you can actually edit.
 *
 * The naive controlled pattern (`value={n}` + `onChange={e => setN(Number(e))}`
 * with a `Math.max(1, …)` guard) makes the field impossible to clear: the moment
 * you delete the last digit the value snaps back, so changing "1" to "2" means
 * appending then deleting — exactly the annoyance we're fixing.
 *
 * Instead we keep a local *draft* string as the source of truth for what's shown,
 * so the field can be blank mid-edit. Parsing/propagation happens as you type;
 * range-clamping waits until blur so the caret is never fought. A focus guard
 * stops incoming props from stomping the draft while you're typing (they still
 * sync on external resets when the field is idle).
 *
 * Every numeric field in the app uses this, so they all behave identically.
 */
export type NumberFieldProps = {
  /** Committed value, or null/undefined when the field is blank. */
  value: number | null | undefined;
  /** Fires with the parsed number, or null when the field is cleared. */
  onValueChange: (value: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
  id?: string;
  name?: string;
  /**
   * When false, a blank field resolves to `min` (or 0) on blur instead of
   * staying empty — for required counts like "travellers" that must be ≥ 1.
   * Defaults to true (optional fields such as budget stay blank).
   */
  allowEmpty?: boolean;
  "aria-label"?: string;
};

const clamp = (n: number, min?: number, max?: number) => {
  if (min != null && n < min) return min;
  if (max != null && n > max) return max;
  return n;
};

const toDraft = (v: number | null | undefined) => (v == null ? "" : String(v));

export function NumberField({
  value,
  onValueChange,
  min,
  max,
  step = 1,
  placeholder,
  className,
  disabled,
  id,
  name,
  allowEmpty = true,
  ...aria
}: NumberFieldProps) {
  const [draft, setDraft] = useState(() => toDraft(value));
  const focused = useRef(false);

  // Reflect external changes (form reset, "use my saved budget", etc.) — but
  // only while the user is NOT typing, so we never clobber an in-progress edit.
  useEffect(() => {
    if (!focused.current) setDraft(toDraft(value));
  }, [value]);

  return (
    <input
      type="number"
      // Whole steps get the numeric keypad; fractional steps get the decimal one.
      inputMode={Number.isInteger(step) ? "numeric" : "decimal"}
      id={id}
      name={name}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      placeholder={placeholder}
      aria-label={aria["aria-label"]}
      value={draft}
      onFocus={() => {
        focused.current = true;
      }}
      onChange={(event) => {
        const raw = event.target.value;
        setDraft(raw);
        if (raw.trim() === "") {
          onValueChange(null);
          return;
        }
        const n = Number(raw);
        // Ignore partials like "-" or "1." — wait for a parseable number.
        if (!Number.isNaN(n)) onValueChange(n);
      }}
      onBlur={() => {
        focused.current = false;
        const raw = draft.trim();
        if (raw === "") {
          if (allowEmpty) {
            onValueChange(null);
          } else {
            const fallback = min ?? 0;
            setDraft(String(fallback));
            onValueChange(fallback);
          }
          return;
        }
        const n = Number(raw);
        if (Number.isNaN(n)) {
          // Unparseable leftover ("--", "1e") — restore the last good value.
          setDraft(toDraft(value));
          return;
        }
        const clamped = clamp(n, min, max);
        setDraft(String(clamped));
        onValueChange(clamped);
      }}
      className={cn("input-field", className)}
    />
  );
}
