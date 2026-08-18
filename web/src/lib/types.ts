/**
 * Shared API types.
 *
 * These mirror the backend's Pydantic models. Where a field encodes a *claim*
 * about trust — `source`, `verified`, `bookable` — the type keeps them separate
 * rather than collapsing them into one boolean, because the UI has to show the
 * difference between "a booking API will hold this fare" and "an agent read this
 * number on a web page".
 */

export type OptionSource =
  | "atlas"
  | "amadeus"
  | "camofox"
  | "llm"
  | "mock"
  | "research";

export type HalalConfidence = "certified" | "muslim_friendly" | "unverified";

export interface PlanOption {
  id: string;
  kind: "flight" | "hotel" | "activity" | "restaurant" | "transport";
  title: string;
  price_amount: number | null;
  price_currency: string | null;
  provider: string | null;
  booking_url: string | null;
  reasoning: string | null;
  halal_confidence: HalalConfidence | null;
  verified: boolean;
  last_checked: string | null;
  /** Which source produced this option. Drives the result badge. */
  source: OptionSource | null;
  /** For crawled options, the page the agent actually read. */
  source_url: string | null;
  /** True when this option can be carried into a real booking flow. */
  bookable: boolean;
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

/** Which panels a scope's result should render, and which agents produced it. */
export interface ScopeMeta {
  slug: string;
  label: string;
  panels: string[];
  agents: string[];
}

export type PlanResults = Record<string, AgentPlanResult> & {
  _scope?: ScopeMeta;
};

/**
 * Agent results only, with the `_scope` metadata key filtered out.
 *
 * `PlanResults` is an intersection so `results.flight` stays conveniently typed,
 * but that makes `Object.entries` yield `AgentPlanResult | ScopeMeta`. Iterating
 * through this helper keeps callers honest instead of casting at every use.
 */
export function agentEntries(
  results: PlanResults,
): Array<[string, AgentPlanResult]> {
  return Object.entries(results).filter(
    (entry): entry is [string, AgentPlanResult] =>
      !entry[0].startsWith("_") &&
      typeof entry[1] === "object" &&
      entry[1] !== null &&
      "summary" in entry[1],
  );
}

export interface PlanResponse {
  results: PlanResults;
  scope: string;
  history_id: string | null;
  duration_ms: number;
}

// --------------------------------------------------------------------------- //
// Scopes
// --------------------------------------------------------------------------- //

/** Which extra inputs a scope wants collected before it runs. */
export type ScopeInput = "goal" | "dates" | "travellers" | "budget" | "pace";

export interface Scope {
  slug: string;
  label: string;
  description: string;
  cta: string;
  icon: string;
  placeholder: string;
  panels: string[];
  agents: string[];
  agent_count: number;
  use_critic: boolean;
  auto_itinerary: boolean;
  estimate_seconds: number;
  inputs: ScopeInput[];
  extras: Record<string, unknown>;
}

// --------------------------------------------------------------------------- //
// API Vault
// --------------------------------------------------------------------------- //

export type CredentialStatus =
  | "untested"
  | "healthy"
  | "rate_limited"
  | "limit_reached"
  | "invalid"
  | "disabled";

export interface Credential {
  id: string;
  provider: string;
  label: string;
  category: string;
  /** A hint like `sk-…4f2a`. The full secret is never returned. */
  masked_secret: string;
  extra: Record<string, unknown>;
  enabled: boolean;
  status: CredentialStatus;
  status_detail: string | null;
  last_tested_at: string | null;
  created_at: string | null;
}

export interface VaultProvider {
  slug: string;
  label: string;
  category: string;
  category_label: string;
  needs_secret: boolean;
  extra_fields: string[];
  docs_url: string | null;
  note: string | null;
  /** True for services that work without any credential at all. */
  keyless: boolean;
  configured: boolean;
  /** Where the credential came from — the vault, or a legacy `.env` value. */
  source: "vault" | "env" | null;
  credential: Credential | null;
}

export interface VaultCatalogue {
  categories: Record<string, string>;
  providers: VaultProvider[];
}

export interface ProbeVerdict {
  status: CredentialStatus;
  ok: boolean;
  message: string;
  latency_ms: number;
}

// --------------------------------------------------------------------------- //
// Engine (AI models)
// --------------------------------------------------------------------------- //

export interface QuotaUsage {
  counts: { rpm: number; rpd: number; tpd: number };
  limits: {
    rpm: number | null;
    rpd: number | null;
    tpd: number | null;
  };
  metered_locally: boolean;
  note: string;
}

export interface LlmProvider {
  id: string;
  name: string;
  litellm_model: string;
  masked_key: string;
  priority: number;
  enabled: boolean;
  max_rpm: number | null;
  max_rpd: number | null;
  max_tpd: number | null;
  status: CredentialStatus;
  status_detail: string | null;
  cooling_down: boolean;
  last_tested_at: string | null;
  last_used_at: string | null;
  created_at: string | null;
  usage?: QuotaUsage;
}

export interface ModelPreset {
  value: string;
  label: string;
  tag?: string;
}

export interface ProviderPreset {
  provider: string;
  name: string;
  icon: string;
  env_var: string | null;
  signup_url: string;
  free_tier: boolean;
  note?: string;
  suggested?: { max_rpm?: number; max_rpd?: number; max_tpd?: number };
  models: ModelPreset[];
}

/** One model the provider itself reported, via /engine/models. */
export interface DiscoveredModel {
  value: string;
  label: string;
  id: string;
  context: number | null;
  free: boolean;
  owned_by: string | null;
}

export interface EngineCatalogue {
  presets: ProviderPreset[];
  ollama_fallback: { enabled: boolean; model: string; note: string };
}

export interface EngineStat {
  model: string;
  calls: number;
  ok: number;
  failed: number;
  tokens_in: number;
  tokens_out: number;
  avg_latency_ms: number | null;
}

// --------------------------------------------------------------------------- //
// Atlas booking
// --------------------------------------------------------------------------- //

export type BookingStage =
  | "draft"
  | "price_confirmed"
  | "ordered"
  | "paying"
  | "paid"
  | "ticketed"
  | "failed";

export interface AtlasEnvelopeSummary {
  status: string;
  code: string;
  message: string;
  needs_action: boolean;
  retryable: boolean;
  request_id: string | null;
  details: Record<string, unknown>;
}

export interface FlightBooking {
  id: string;
  trip_id: string | null;
  offer_id: string | null;
  booking_id: string | null;
  order_no: string | null;
  has_confirmation: boolean;
  environment: "sandbox" | "production";
  stage: BookingStage;
  last_code: string | null;
  last_message: string | null;
  route: string | null;
  depart_date: string | null;
  travellers: number;
  total_amount: number | null;
  currency: string | null;
  /** True for a sandbox rehearsal — no real money moved. */
  simulated: boolean;
  payload: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
  // Step responses
  atlas?: AtlasEnvelopeSummary;
  requires_confirmation?: boolean;
  reason?: string;
  previous_amount?: number | null;
  new_amount?: number | null;
  payment_summary?: string | null;
  order_link?: string | null;
  ready_to_pay?: boolean;
  next?: string | null;
  warning?: string;
  tickets?: Array<Record<string, unknown>>;
  ancillaries?: {
    baggage: Array<Record<string, unknown>>;
    seats: Array<Record<string, unknown>>;
    note?: string;
  };
}

export interface AtlasStatus {
  installed: boolean;
  authorised: boolean;
  environment: string | null;
  code?: string;
  detail: string;
}

// --------------------------------------------------------------------------- //
// History
// --------------------------------------------------------------------------- //

export interface HistoryEntry {
  id: string;
  trip_id: string | null;
  scope: string;
  goal: string;
  destination: string | null;
  origin: string | null;
  agent_count: number;
  duration_ms: number | null;
  option_count: number;
  created_at: string;
  result_snapshot?: PlanResults;
}
