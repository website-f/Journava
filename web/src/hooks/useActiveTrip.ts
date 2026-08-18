import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePlanStore, type AgentPlanResult } from "@/stores/planStore";

/**
 * Hydrate the plan store from `GET /trip` when it is empty.
 *
 * The store only holds what the current tab planned, so any page that reads it
 * directly shows an empty state after a reload or a deep link — even though the
 * backend still has the active trip. Every surface that renders trip data should
 * call this so they all agree on what the active trip is.
 *
 * Returns `loading` for the first fetch only; once the store has results the
 * hook is a no-op and never re-fetches over newer local state.
 */
export function useActiveTrip() {
  const results = usePlanStore((s) => s.results);
  const setResults = usePlanStore((s) => s.setResults);
  const [loading, setLoading] = useState(results === null);

  useEffect(() => {
    if (results !== null) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ trip: Record<string, AgentPlanResult> | null }>(
          "/trip",
        );
        if (!cancelled && res.trip) setResults(res.trip);
      } catch {
        // No active trip yet — the caller renders its empty state.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // Deliberately keyed on nothing but mount: `results` becoming non-null must
    // not retrigger a fetch, and `setResults` is stable in zustand.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { results, loading };
}
