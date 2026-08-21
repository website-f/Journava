/**
 * Money — renders a price in the user's chosen display currency, converting from
 * the price's native currency via live FX. Falls back to the native currency if
 * rates aren't available yet. CurrencySwitcher sets the display currency.
 */

import { Select } from "@/components/ui/Select";
import { CURRENCIES } from "@/lib/currencies";
import { convert, formatMoney, useCurrency, useRates } from "@/lib/money";

export function Money({
  amount,
  currency,
}: {
  amount?: number | string | null;
  currency?: string | null;
}) {
  const display = useCurrency((s) => s.display);
  const rates = useRates(display);

  if (amount === null || amount === undefined || amount === "") return <>—</>;
  const amt = Number(amount);
  if (Number.isNaN(amt)) return <>—</>;

  const from = (currency || display).toUpperCase();
  const converted = convert(amt, from, display, rates);
  return <>{converted == null ? formatMoney(amt, from) : formatMoney(converted, display)}</>;
}

export function CurrencySwitcher({ className }: { className?: string }) {
  const display = useCurrency((s) => s.display);
  const setDisplay = useCurrency((s) => s.setDisplay);
  return (
    <Select
      value={display}
      onValueChange={setDisplay}
      aria-label="Display currency"
      options={CURRENCIES}
      renderValue={(v) => v}
      className={className}
    />
  );
}
