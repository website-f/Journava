/**
 * Plan store — the result of the most recent run, shared across surfaces.
 *
 * Keyed by scope as well as holding the "current" result: a flights-only lookup
 * should not overwrite the full trip the traveller is working from, so the two
 * live side by side and each surface reads the one it cares about.
 */

import { create } from "zustand";
import { api } from "@/lib/api";
import type { PlanResults, ScopeMeta } from "@/lib/types";

/** The `/jobs/{id}` record for a backgrounded plan run. */
interface PlanJobRecord {
  id: string;
  status: "queued" | "running" | "done" | "error";
  result: {
    results: PlanResults;
    scope: string;
    history_id: string | null;
    duration_ms: number;
  } | null;
  /** Accumulated results while still running — streamed tier-by-tier. */
  partial: PlanResults | null;
  error: string | null;
}

const POLL_INTERVAL_MS = 2000;
// A full trip (21 agents + critic re-runs + live crawls) can take several
// minutes. The job runs in the background regardless — this is only how long the
// foreground poll waits before backing off, so keep it generous.
const POLL_TIMEOUT_MS = 1_200_000; // 20 min

export type {
  AgentPlanResult,
  ItineraryItem,
  PlanOption,
  PlanResults,
  ScopeMeta,
} from "@/lib/types";

export interface CostDetail {
  original_cost: number | null;
  replacement_cost: number | null;
  additional_cost: number | null;
  currency: string;
  /** False when either side had no priced option — the delta is not a real zero. */
  comparable: boolean;
}

export interface DisruptionRecovery {
  disruption_type: string;
  recovery_plan: PlanResults;
  additional_cost: string;
  cost_detail: CostDetail;
  agents_activated: string[];
  summary: string;
}

/** Extra inputs the scoped Command Center collects alongside the goal. */
export interface PlanInputs {
  goal: string;
  start_date: string;
  end_date: string;
  travellers: number;
  budget_amount: number | null;
  budget_currency: string;
  pace: "relaxed" | "balanced" | "packed";
}

export const EMPTY_INPUTS: PlanInputs = {
  goal: "",
  start_date: "",
  end_date: "",
  travellers: 1,
  budget_amount: null,
  budget_currency: "MYR",
  pace: "balanced",
};

export interface PlanState {
  /** The most recent result, whatever its scope. */
  results: PlanResults | null;
  /** Results per scope, so a narrow lookup never clobbers the full trip. */
  byScope: Record<string, PlanResults>;
  activeScope: string | null;
  lastDurationMs: number | null;
  lastHistoryId: string | null;

  loading: boolean;
  error: string | null;

  /** A backgrounded plan job is in flight — drives the "agents working" modal.
   *  Lives in the store (not a component) so it survives navigation: the user
   *  can jump to the Agents Workspace and the run keeps going. */
  jobRunning: boolean;
  jobId: string | null;
  /** True while a run is streaming partial results (some sections in, more
   *  still landing) — drives the inline "agents still working" banner. */
  streaming: boolean;

  inputs: PlanInputs;

  recovery: DisruptionRecovery | null;
  recoveryLoading: boolean;

  setResults: (results: PlanResults, scope?: string, meta?: {
    durationMs?: number;
    historyId?: string | null;
  }) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  /** Dispatch a background plan job and poll it to completion. Never throws —
   *  it sets `results` on success or `error` on failure. */
  runPlanJob: (payload: Record<string, unknown>) => Promise<void>;
  setInputs: (patch: Partial<PlanInputs>) => void;
  resetInputs: (goal?: string) => void;
  setRecovery: (recovery: DisruptionRecovery | null) => void;
  setRecoveryLoading: (loading: boolean) => void;
  resultsFor: (scope: string) => PlanResults | null;
  clear: () => void;
}

function scopeOf(results: PlanResults, fallback?: string): string {
  const meta = results._scope as ScopeMeta | undefined;
  return meta?.slug ?? fallback ?? "full_trip";
}

export const usePlanStore = create<PlanState>((set, get) => ({
  results: null,
  byScope: {},
  activeScope: null,
  lastDurationMs: null,
  lastHistoryId: null,
  loading: false,
  error: null,
  jobRunning: false,
  jobId: null,
  streaming: false,
  inputs: { ...EMPTY_INPUTS },
  recovery: null,
  recoveryLoading: false,

  setResults: (results, scope, meta) => {
    const slug = scopeOf(results, scope);
    set((state) => ({
      results,
      activeScope: slug,
      byScope: { ...state.byScope, [slug]: results },
      lastDurationMs: meta?.durationMs ?? state.lastDurationMs,
      lastHistoryId: meta?.historyId ?? state.lastHistoryId,
      loading: false,
      error: null,
    }));
  },

  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error, loading: false }),

  runPlanJob: async (payload) => {
    set({ jobRunning: true, streaming: false, error: null });
    const jobScope = String((payload as { scope?: string }).scope || "full_trip");
    try {
      const created = await api.post<{ id: string }>("/jobs/plan", payload);
      set({ jobId: created.id });

      const startedAt = Date.now();
      // Poll until the job finishes. A newer run (different jobId) or a clear()
      // supersedes this loop, so stale polls can't overwrite fresh results.
      for (;;) {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        if (get().jobId !== created.id) return;

        const job = await api.get<PlanJobRecord>(`/jobs/${created.id}`);
        if (job.status === "done" && job.result) {
          const { results, scope, history_id, duration_ms } = job.result;
          get().setResults(results, scope, {
            durationMs: duration_ms,
            historyId: history_id,
          });
          set({ jobRunning: false, streaming: false, jobId: null });
          return;
        }
        // Stream partial results as tiers land — the traveller browses flights/
        // stays/places while the itinerary is still assembling.
        if (job.partial && Object.keys(job.partial).length > 0) {
          get().setResults(job.partial, jobScope);
          set({ streaming: true });
        }
        if (job.status === "error") {
          set({ jobRunning: false, streaming: false, jobId: null, error: job.error ?? "Planning failed" });
          return;
        }
        if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
          // The backend job keeps running; we just stop the foreground poll.
          set({
            jobRunning: false,
            streaming: false,
            jobId: null,
            error:
              "Still planning in the background — check the Agents workspace, or we'll notify you if Telegram is connected.",
          });
          return;
        }
      }
    } catch (error) {
      set({
        jobRunning: false,
        streaming: false,
        jobId: null,
        error: error instanceof Error ? error.message : "Planning failed",
      });
    }
  },

  setInputs: (patch) =>
    set((state) => ({ inputs: { ...state.inputs, ...patch } })),
  resetInputs: (goal = "") => set({ inputs: { ...EMPTY_INPUTS, goal } }),

  setRecovery: (recovery) => set({ recovery, recoveryLoading: false }),
  setRecoveryLoading: (recoveryLoading) => set({ recoveryLoading }),

  resultsFor: (scope) => get().byScope[scope] ?? null,

  clear: () =>
    set({
      results: null,
      byScope: {},
      activeScope: null,
      recovery: null,
      loading: false,
      error: null,
      jobRunning: false,
      streaming: false,
      jobId: null,
      lastDurationMs: null,
      lastHistoryId: null,
    }),
}));
