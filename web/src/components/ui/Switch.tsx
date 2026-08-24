/**
 * Switch — the app's toggle control (Aurora).
 *
 * Two separate things kept deforming this pill, and both are guarded here:
 *
 * 1. Dimensions and the thumb offset are INLINE styles, not Tailwind
 *    width/translate utilities, because those weren't reliably applied in the
 *    production CSS build and let the track collapse to the thumb's width.
 *
 * 2. `data-fixed-size` opts the track out of the global coarse-pointer
 *    `min-height: 44px` touch-target rule. That rule beats an inline `height`
 *    (min-height always does), so on phones the 52×28 pill inflated into a
 *    52×44 squat box while desktop — a fine pointer — stayed correct. That was
 *    the "squeezed on mobile only" bug. The finger still gets its 44px: the
 *    `tap-target` utility grows the HIT area with a pseudo-element instead of
 *    growing what's painted.
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
      data-fixed-size=""
      // min-* as well as the exact size: nothing in a flex row may squeeze the
      // track, and nothing in the cascade may stretch it.
      style={{ width: 52, minWidth: 52, height: 28, minHeight: 28 }}
      className={cn(
        "tap-target relative shrink-0 rounded-[var(--r-pill)]",
        "transition-colors duration-[var(--dur)] ease-[var(--ease)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked
          ? "bg-[var(--brand-500)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.18)]"
          : "bg-[var(--border)] shadow-[inset_0_1px_2px_rgba(0,0,0,0.08)]",
        className,
      )}
    >
      <SwitchPrimitive.Thumb
        style={{
          width: 24,
          height: 24,
          transform: `translateX(${checked ? 26 : 2}px)`,
        }}
        // Spring easing on the thumb only — the track's colour crossfade should
        // stay linear-ish, but the knob wants a little physical overshoot.
        className="block rounded-full bg-white shadow-[var(--shadow-1)] transition-transform duration-[var(--dur)] ease-[var(--ease-spring)]"
      />
    </SwitchPrimitive.Root>
  );
}
