/**
 * Switch — the app's toggle control (Aurora).
 *
 * Dimensions and the thumb offset are INLINE styles, not Tailwind width/translate
 * utilities, because those weren't reliably applied in the production CSS build
 * and let the track collapse to the thumb's width (a squashed near-square). Inline
 * styles can't be dropped by the CSS pipeline, so the pill can never regress.
 */

import * as SwitchPrimitive from "@radix-ui/react-switch";
import { cn } from "@/lib/cn";

interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  "aria-label"?: string;
  className?: string;
}

export function Switch({
  checked,
  onCheckedChange,
  disabled,
  className,
  "aria-label": ariaLabel,
}: SwitchProps) {
  return (
    <SwitchPrimitive.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={ariaLabel}
      style={{ width: 52, height: 28 }}
      className={cn(
        "relative shrink-0 rounded-[var(--r-pill)] transition-colors duration-[var(--dur)] ease-[var(--ease)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] disabled:opacity-50",
        checked ? "bg-[var(--brand-500)]" : "bg-[var(--border)]",
        className,
      )}
    >
      <SwitchPrimitive.Thumb
        style={{
          width: 24,
          height: 24,
          transform: `translateX(${checked ? 26 : 2}px)`,
        }}
        className="block rounded-full bg-white shadow-[var(--shadow-1)] transition-transform duration-[var(--dur)]"
      />
    </SwitchPrimitive.Root>
  );
}
