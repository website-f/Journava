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
 * Fetches `GET /trip` on every mount and reconciles: the server's saved trip is
 * authoritative for the trip surface. Previously it skipped the fetch whenever
 * the shared store already held *anything*, so a leftover scoped search (e.g. a
 * flights-only result) masked the real saved trip until a full page refresh —
 * that's the "only works after refresh" symptom on the trip page. It only
 * overwrites when the server actually returns a trip, so a just-planned (unsaved)
 * plan still survives, and edits made on the trip surface persist server-side so
 * they come back on the next mount.
 */
export function useActiveTrip() {
  const results = usePlanStore((s) => s.results);
  const setResults = usePlanStore((s) => s.setResults);
  const [loading, setLoading] = useState(results === null);

  useEffect(() => {
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
    // Runs once per mount to reconcile with the server. `setResults` is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { results, loading };
}
