/**
 * Plan store — the result of the most recent run, shared across surfaces.
 *
 * Keyed by scope as well as holding the "current" result: a flights-only lookup
 * should not overwrite the full trip the traveller is working from, so the two
 * live side by side and each surface reads the one it cares about.
 */

import { create } from "zustand";
import type { PlanResults, ScopeMeta } from "@/lib/types";

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
  budget_amount: string;
  budget_currency: string;
  pace: "relaxed" | "balanced" | "packed";
}

export const EMPTY_INPUTS: PlanInputs = {
  goal: "",
  start_date: "",
  end_date: "",
  travellers: 1,
  budget_amount: "",
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

  inputs: PlanInputs;

  recovery: DisruptionRecovery | null;
  recoveryLoading: boolean;

  setResults: (results: PlanResults, scope?: string, meta?: {
    durationMs?: number;
    historyId?: string | null;
  }) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
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
      lastDurationMs: null,
      lastHistoryId: null,
    }),
}));
