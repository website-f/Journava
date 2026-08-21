import { useEffect, useState } from "react";
import { create } from "zustand";
import { api } from "@/lib/api";

/**
 * Display-currency state + FX conversion for the results surface.
 *
 * Agents price in the traveller's budget currency; the switcher lets them view
 * every price in any currency. Rates come from GET /rates?base=<display> and are
 * expressed as units-per-1-base, so converting a price of `amount` in currency C
 * to the display base is `amount / rates[C]`.
 */

interface CurrencyState {
  display: string;
  setDisplay: (currency: string) => void;
}

export const useCurrency = create<CurrencyState>((set) => ({
  display: "MYR",
  setDisplay: (display) => set({ display }),
}));

const _ratesCache = new Map<string, Record<string, number>>();

export function useRates(base: string): Record<string, number> | null {
  const [rates, setRates] = useState<Record<string, number> | null>(
    _ratesCache.get(base) ?? null,
  );
  useEffect(() => {
    let cancelled = false;
    const cached = _ratesCache.get(base);
    if (cached) {
      setRates(cached);
      return;
    }
    (async () => {
      try {
        const res = await api.get<{ base: string; rates: Record<string, number> }>(
          `/rates?base=${encodeURIComponent(base)}`,
        );
        if (!cancelled && res?.rates) {
          _ratesCache.set(base, res.rates);
          setRates(res.rates);
        }
      } catch {
        // Leave null — prices then show in their native currency.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [base]);
  return rates;
}

/** Convert `amount` from currency `from` into `to`, using rates keyed to base=`to`. */
export function convert(
  amount: number,
  from: string,
  to: string,
  rates: Record<string, number> | null,
): number | null {
  if (from === to) return amount;
  if (!rates) return null;
  const rate = rates[from]; // units of `from` per 1 `to`
  if (!rate) return null;
  return amount / rate;
}

export function formatMoney(amount: number, currency: string): string {
  return `${currency} ${amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
