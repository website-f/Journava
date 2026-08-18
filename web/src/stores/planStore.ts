/**
 * Plan store — holds the latest plan results so Command Center + Research Board
 * can both read from it without re-fetching. Uses zustand (spec §6).
 *
 * Phase 2: also holds the active trip (loaded from GET /trip) and disruption
 * recovery state for the My Trip page.
 */

import { create } from "zustand";

export interface PlanOption {
  id: string;
  kind: "flight" | "hotel" | "activity" | "restaurant" | "transport";
  title: string;
  price_amount: number | null;
  price_currency: string | null;
  provider: string | null;
  booking_url: string | null;
  reasoning: string | null;
  halal_confidence: "certified" | "muslim_friendly" | "unverified" | null;
  verified: boolean;
  last_checked: string | null;
  raw: Record<string, unknown>;
}

export interface ItineraryItem {
  day_index: number;
  kind: "flight" | "hotel" | "activity" | "meal" | "transport";
  title: string;
  starts_at: string | null;
  ends_at: string | null;
  reasoning: string | null;
  cost_amount: number | null;
  cost_currency: string | null;
  details: Record<string, unknown>;
}

export interface AgentPlanResult {
  agent: string;
  summary: string;
  options: PlanOption[];
  items: ItineraryItem[];
  applied_preferences: Record<string, string>;
  warnings: string[];
  data: Record<string, unknown>;
}

export interface DisruptionRecovery {
  disruption_type: string;
  recovery_plan: Record<string, AgentPlanResult>;
  additional_cost: string;
  agents_activated: string[];
  summary: string;
}

export interface PlanState {
  results: Record<string, AgentPlanResult> | null;
  loading: boolean;
  error: string | null;
  /** Disruption recovery result (shown in My Trip). */
  recovery: DisruptionRecovery | null;
  recoveryLoading: boolean;
  setResults: (results: Record<string, AgentPlanResult>) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setRecovery: (recovery: DisruptionRecovery | null) => void;
  setRecoveryLoading: (loading: boolean) => void;
  clear: () => void;
}

export const usePlanStore = create<PlanState>((set) => ({
  results: null,
  loading: false,
  error: null,
  recovery: null,
  recoveryLoading: false,
  setResults: (results) => set({ results, loading: false, error: null }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error, loading: false }),
  setRecovery: (recovery) => set({ recovery, recoveryLoading: false }),
  setRecoveryLoading: (recoveryLoading) => set({ recoveryLoading }),
  clear: () => set({ results: null, loading: false, error: null, recovery: null }),
}));
