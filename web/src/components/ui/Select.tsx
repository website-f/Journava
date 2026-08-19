import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

/**
 * Custom Select built on Radix — never a native <select> (spec §10.3).
 * Keyboard + screen-reader accessible, animated panel, custom chevron.
 */
export type SelectOption = { value: string; label: string; disabled?: boolean };

/** A labelled cluster of options — the accessible replacement for `<optgroup>`. */
export type SelectGroup = { label: string; options: SelectOption[] };

type SelectProps = {
  value?: string;
  onValueChange?: (value: string) => void;
  /** Flat options. Ignored when `groups` is provided. */
  options?: SelectOption[];
  /** Grouped options, rendered with Radix `Group` + `Label`. */
  groups?: SelectGroup[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
};

export function Select({
  value,
  onValueChange,
  options = [],
  groups,
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
          <SelectPrimitive.Viewport className="overflow-y-auto p-0">
            {groups
              ? groups.map((group) => (
                  <SelectPrimitive.Group key={group.label}>
                    <SelectPrimitive.Label className="px-3 pb-1 pt-2 text-[0.7rem] font-semibold uppercase tracking-wide text-[var(--muted)]">
                      {group.label}
                    </SelectPrimitive.Label>
                    {group.options.map((option) => (
                      <SelectItem key={option.value} option={option} />
                    ))}
                  </SelectPrimitive.Group>
                ))
              : options.map((option) => (
                  <SelectItem key={option.value} option={option} />
                ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

/** One selectable row. Shared by the flat and grouped renderings. */
function SelectItem({ option }: { option: SelectOption }) {
  return (
    <SelectPrimitive.Item
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
  );
}
