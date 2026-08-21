import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AgentPlanResult } from "@/stores/planStore";

type TripResults = Record<string, AgentPlanResult> | null;

/**
 * The user's SAVED trip, fetched from `GET /trip`.
 *
 * A trip only exists after the traveller taps "Add to my trip" (which POSTs
 * /trip/save). This hook intentionally does NOT fall back to the transient plan
 * store, so a plan you merely *searched* for no longer shows up on the Trip page
 * before you've added it. Fetched fresh on every mount, so navigating in from a
 * scoped search never shows stale data until a manual refresh.
 *
 * `setTrip` lets the trip surface update the trip in place after an
 * edit / refine / delete, without a refetch.
 */
export function useActiveTrip() {
  const [results, setResults] = useState<TripResults>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ trip: TripResults }>("/trip");
        if (!cancelled) setResults(res.trip ?? null);
      } catch {
        // No saved trip yet — the caller renders its empty state.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return { results, loading, setTrip: setResults };
}
