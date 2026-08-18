import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";

/**
 * Custom Select built on Radix — never a native <select> (spec §10.3).
 * Keyboard + screen-reader accessible, animated panel, custom chevron.
 */
export type SelectOption = { value: string; label: string; disabled?: boolean };

type SelectProps = {
  value?: string;
  onValueChange?: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
};

export function Select({
  value,
  onValueChange,
  options,
  placeholder = "Choose…",
  disabled,
  className,
  ...aria
}: SelectProps) {
  return (
    <SelectPrimitive.Root
      value={value}
      onValueChange={onValueChange}
      disabled={disabled}
    >
      <SelectPrimitive.Trigger
        aria-label={aria["aria-label"]}
        className={cn(
          "h-11 w-full rounded-[var(--r-md)] border border-[var(--border)]",
          "bg-[var(--surface)] px-4 flex items-center justify-between gap-2",
          "text-left text-[var(--text)] transition-colors duration-[var(--dur)]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
          "data-[state=open]:border-[var(--brand-400)]",
          "data-[placeholder]:text-[var(--muted)]",
          "disabled:opacity-60 disabled:pointer-events-none",
          className,
        )}
      >
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon>
          <ChevronDown className="h-4 w-4 opacity-60" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>

      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={6}
          className={cn(
            "radix-panel z-[70] min-w-[var(--radix-select-trigger-width)]",
            "max-h-[min(20rem,var(--radix-select-content-available-height))]",
            "overflow-hidden rounded-[var(--r-md)] border border-[var(--border)]",
            "bg-[var(--elevated)] shadow-[var(--shadow-2)] p-1",
          )}
        >
          <SelectPrimitive.Viewport className="p-0">
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={option.value}
                disabled={option.disabled}
                className={cn(
                  "relative flex cursor-pointer select-none items-center",
                  "gap-2 rounded-[var(--r-sm)] py-2.5 pl-3 pr-8 text-sm outline-none",
                  "data-[highlighted]:bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)]",
                  "data-[state=checked]:text-[var(--brand-500)]",
                  "data-[disabled]:opacity-50 data-[disabled]:pointer-events-none",
                )}
              >
                <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator className="absolute right-2.5">
                  <Check className="h-4 w-4" />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
