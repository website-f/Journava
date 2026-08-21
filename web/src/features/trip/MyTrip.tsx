import { Suspense, lazy, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Briefcase, AlertTriangle, Zap, TrendingUp, Cloud, Calendar, Clock, GripHorizontal, Plane, ShieldAlert, ShieldCheck, Sparkles, Trash2, Newspaper, ArrowUp, ArrowDown, CheckCircle2 } from "@/components/ui/icons";
import { Button, Badge, EmptyState, LoadingOverlay, OptionCard, Select, Skeleton, confirm } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import { Money } from "@/components/ui/Money";
import { cn } from "@/lib/cn";

// MapLibre is ~1MB; load it only when this page actually renders.
const TripMap = lazy(() =>
  import("@/components/ui/TripMap").then((m) => ({ default: m.TripMap })),
);
import { api } from "@/lib/api";
import { usePlanStore } from "@/stores/planStore";
import type { AgentPlanResult, CostDetail, DisruptionRecovery, ItineraryItem, PlanResults } from "@/stores/planStore";
import { useAgentStream } from "@/hooks/useAgentStream";
import { useActiveTrip } from "@/hooks/useActiveTrip";
import { agentEntries } from "@/lib/types";
import { TripExtraPanels } from "@/features/command-center/ScopedResults";

/** Days-to-go from the trip's start date (found in the chief's resolved request). */
function tripStartDate(results: Record<string, AgentPlanResult>): Date | null {
  const data = (results.chief?.data ?? {}) as Record<string, unknown>;
  const resolved = (data.resolved_request ?? {}) as Record<string, unknown>;
  const raw = (resolved.start_date ?? data.start_date) as string | undefined;
  if (!raw) return null;
  const d = new Date(raw);
  return Number.isNaN(d.getTime()) ? null : d;
}

function countdownLabel(start: Date | null): string | null {
  if (!start) return null;
  const days = Math.ceil((start.getTime() - Date.now()) / 86_400_000);
  if (days > 1) return `${days} days to go`;
  if (days === 1) return "Tomorrow!";
  if (days === 0) return "Today!";
  return "Trip underway / past";
}

/**
 * My Trip (spec section 3.3) — day-by-day itinerary, budget tracker, weather,
 * and the disruption simulation "money shot".
 */
export function MyTrip() {
  const { recovery, setRecovery, recoveryLoading, setRecoveryLoading } = usePlanStore();
  const { events } = useAgentStream();
  // Shared with the Research Board so both surfaces agree on the active trip.
  const { results, loading: tripLoading, setTrip } = useActiveTrip();

  const handleCancelRecovery = async () => {
    const ok = await confirm({
      title: "Cancel recovery?",
      body: "Agents are still rebuilding your trip. Stop the recovery?",
      confirmText: "Cancel",
    });
    if (!ok) return;
    try {
      await api.post("/cancel");
      setRecoveryLoading(false);
      toast.info("Recovery cancelled.");
    } catch {
      // ignore
    }
  };

  const handleDeleteTrip = async () => {
    const ok = await confirm({
      title: "Remove this trip?",
      body: "Your active trip is cleared. Past searches stay in History.",
      confirmText: "Remove trip",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del("/trip");
      usePlanStore.getState().clear();
      setTrip(null);
      toast.success("Trip removed.");
    } catch {
      toast.error("Could not remove the trip.");
    }
  };

  if (tripLoading) {
    return (
      <div className="mx-auto w-full max-w-5xl">
        <TripHeader />
        {/* Skeletons rather than a spinner, so the layout doesn't shift (§10.6). */}
        <div className="space-y-4">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      </div>
    );
  }

  if (!results) {
    return (
      <div className="mx-auto w-full max-w-5xl">
        <TripHeader />
        <EmptyState
          icon={<Briefcase className="h-10 w-10" />}
          title="No active trip"
          description="Once a plan is accepted it becomes your live trip, with day-by-day detail and a budget tracker."
          action={
            // Router link, not <a>: a full page reload would drop the store.
            <Button asChild variant="secondary">
              <Link to="/">Plan a trip</Link>
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl">
      <LoadingOverlay
        open={recoveryLoading}
        events={events}
        onCancel={handleCancelRecovery}
      />

      <TripHeader results={results} onDelete={handleDeleteTrip} />
      <TripSummary results={results} />
      <RiskBanner results={results} />
      <Suspense fallback={<Skeleton className="mb-6 h-64 w-full" />}>
        <TripMap className="mb-6" />
      </Suspense>
      <BudgetCard results={results} />
      <WeatherCard results={results} />
      <ItinerarySection results={results} setTrip={setTrip} />
      {/* The full plan — flights, stays, food, places, visa, insurance — so the
          saved trip shows everything the agents produced, not just the summary. */}
      <div className="mt-8">
        <TripExtraPanels results={results as PlanResults} />
      </div>
      <FlightWatchCard />
      <DisruptionSection recovery={recovery} setRecovery={setRecovery} setRecoveryLoading={setRecoveryLoading} recoveryLoading={recoveryLoading} />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Autonomous flight-delay watch + budget-aware auto-reschedule
// --------------------------------------------------------------------------- //

type WatchAlt = {
  id: string;
  title: string;
  price_amount: number | null;
  price_currency: string | null;
  bookable: boolean;
  booking_url: string | null;
  within_budget: boolean | null;
};

type WatchResult = {
  disrupted: boolean;
  status: { status: string; delay_minutes: number | null; mode: string; carrier?: string; route?: string } | null;
  reason?: string;
  flight?: { carrier: string; origin: string; destination: string };
  auto_rescheduled?: boolean;
  recovery?: { summary: string; additional_cost: string };
  notified?: boolean;
  alternatives?: WatchAlt[];
  budget?: {
    amount: number | null;
    currency: string;
    within_budget_count: number;
    total_alternatives: number;
    cheapest_within: number | null;
  };
};

const WATCH_MODES = [
  { value: "real", label: "Check live status" },
  { value: "delayed", label: "Demo: delay" },
  { value: "cancelled", label: "Demo: cancellation" },
];

function FlightWatchCard() {
  const [mode, setMode] = useState("real");
  const [auto, setAuto] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<WatchResult | null>(null);

  const run = async () => {
    setLoading(true);
    try {
      const res = await api.post<WatchResult>("/monitor/flight", {
        simulate: mode === "real" ? null : mode,
        auto_reschedule: auto,
        threshold_minutes: 90,
      });
      setResult(res);
      if (res.reason) toast.info(res.reason);
      else if (!res.disrupted) toast.success("Flight looks on track.");
      else toast.warning(res.recovery?.summary ?? "Disruption handled.");
    } catch {
      toast.error("Couldn't check the flight status.");
    } finally {
      setLoading(false);
    }
  };

  const s = result?.status;
  const b = result?.budget;

  return (
    <section className="mt-8">
      <div className="surface-card p-5">
        <div className="mb-3 flex items-center gap-2">
          <Plane className="h-5 w-5 text-[var(--brand-500)]" />
          <h3 className="text-base font-semibold">Flight watch &amp; auto-reschedule</h3>
        </div>
        <p className="mb-4 text-sm text-[var(--muted)]">
          Journava monitors your flight and, if it's delayed or cancelled, automatically finds
          alternatives <strong>within your budget</strong> and alerts you.
        </p>

        <div className="flex flex-wrap items-center gap-3">
          <div className="w-52">
            <Select
              value={mode}
              onValueChange={setMode}
              options={WATCH_MODES}
              aria-label="Status check mode"
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={auto} onCheckedChange={setAuto} aria-label="Auto-reschedule" />
            Auto-reschedule
          </label>
          <Button onClick={run} loading={loading} disabled={loading}>
            <Zap className="h-4 w-4" />
            Check now
          </Button>
        </div>

        {result && (
          <div className="mt-5">
            {result.reason ? (
              <p className="text-sm text-[var(--muted)]">{result.reason}</p>
            ) : !result.disrupted ? (
              <div className="flex items-center gap-2 rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--success)_12%,transparent)] px-3 py-2 text-sm text-[var(--success)]">
                <CheckCircle2 className="h-4 w-4" />
                {s?.carrier ? `${s.carrier} ` : ""}
                {s?.route ?? "Flight"} is {s?.status?.replace(/_/g, " ") ?? "on time"}
                {s?.mode === "simulated" ? " (simulated)" : ""}.
              </div>
            ) : (
              <div className="space-y-4">
                <div className="rounded-[var(--r-md)] border-l-4 border-[var(--warning)] bg-[color-mix(in_srgb,var(--warning)_10%,transparent)] px-4 py-3">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4 text-[var(--warning)]" />
                    <span className="text-sm font-semibold">
                      {s?.carrier} {s?.route} {s?.status?.toUpperCase()}
                      {s?.delay_minutes ? ` · ~${s.delay_minutes} min` : ""}
                    </span>
                    {result.notified && <Badge variant="success">Alerted</Badge>}
                  </div>
                  <p className="mt-1 text-sm text-[var(--muted)]">
                    {result.auto_rescheduled ? "Auto-rescheduled. " : ""}
                    {result.recovery?.summary} · {result.recovery?.additional_cost}
                  </p>
                </div>

                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <h4 className="text-sm font-medium">Alternatives within budget</h4>
                    {b?.amount != null && (
                      <span className="text-xs text-[var(--muted)]">
                        {b.within_budget_count}/{b.total_alternatives} under {b.currency}{" "}
                        {b.amount.toLocaleString()}
                      </span>
                    )}
                  </div>
                  <div className="space-y-2">
                    {(result.alternatives ?? []).map((a) => (
                      <div key={a.id} className="surface-card flex items-center gap-3 p-3">
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-500)]">
                          <Plane className="h-4 w-4" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{a.title}</p>
                          {a.within_budget != null && (
                            <p
                              className={cn(
                                "text-xs",
                                a.within_budget ? "text-[var(--success)]" : "text-[var(--warning)]",
                              )}
                            >
                              {a.within_budget ? "within budget" : "over budget"}
                            </p>
                          )}
                        </div>
                        {a.price_amount != null && (
                          <span className="shrink-0 text-sm font-semibold">
                            <Money amount={a.price_amount} currency={a.price_currency ?? "MYR"} />
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Sub-components
// --------------------------------------------------------------------------- //

function TripHeader({
  results,
  onDelete,
}: {
  results?: Record<string, AgentPlanResult>;
  onDelete?: () => void;
}) {
  const countdown = results ? countdownLabel(tripStartDate(results)) : null;
  return (
    <header className="flex flex-wrap items-start justify-between gap-3 pt-2 pb-6">
      <div className="min-w-0">
        <h2 className="font-[family-name:var(--font-display)] text-2xl tracking-tight">My Trip</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          The full plan — your agents keep monitoring flights, weather and safety after checkout.
        </p>
      </div>
      <div className="flex items-center gap-2">
        {countdown && (
          <span className="inline-flex items-center gap-1.5 rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] px-3 py-1.5 text-sm font-semibold text-[var(--brand-600)]">
            <Clock className="h-4 w-4" />
            {countdown}
          </span>
        )}
        {onDelete && (
          <Button variant="ghost" size="sm" onClick={onDelete}>
            <Trash2 className="h-4 w-4 text-[var(--danger)]" />
            Remove
          </Button>
        )}
      </div>
    </header>
  );
}

function TripSummary({ results }: { results: Record<string, AgentPlanResult> }) {
  const chief = results.chief;
  const data = chief?.data ?? {};
  const destination = (data as Record<string, unknown>).destination as string | undefined;
  const heroImage = (results.research?.data as Record<string, unknown> | undefined)?.hero_image as
    | string
    | undefined;

  return (
    <div className="surface-card mb-6 overflow-hidden border-l-4 border-[var(--brand-500)]">
      {heroImage && (
        <img
          src={heroImage}
          alt={destination ?? "Trip"}
          loading="lazy"
          className="h-40 w-full object-cover"
        />
      )}
      <div className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="text-lg font-semibold">{destination ?? "Your Trip"}</h3>
          {chief?.summary && (
            <Badge variant="brand" className="normal-case">
              {chief.summary}
            </Badge>
          )}
        </div>
      </div>
    </div>
  );
}

function RiskBanner({ results }: { results: Record<string, AgentPlanResult> }) {
  const risk = results.risk_advisory;
  if (!risk?.data) return null;

  const data = risk.data;
  const safetyLevel = data.safety_level as string | undefined;
  const threats = data.active_threats as string[] | undefined;
  // Field names must match what risk_advisory.py actually emits: `safe_months`
  // in `data`, and the advisory text as the result's top-level `summary`.
  const safeMonths = data.safe_months as string[] | undefined;
  const summary = risk.summary;
  const recommendedAction = data.recommended_action as string | undefined;

  if (!safetyLevel || safetyLevel === "safe") {
    // Show a subtle "safe" indicator
    return (
      <div className="surface-card p-3 mb-6 flex items-center gap-3 border-l-4 border-[var(--success)]">
        <ShieldCheck className="h-5 w-5 text-[var(--success)] shrink-0" />
        <div>
          <p className="text-sm font-medium text-[var(--success)]">Destination assessed as safe</p>
          {summary && <p className="text-xs text-[var(--muted)] mt-0.5">{summary}</p>}
        </div>
      </div>
    );
  }

  const isDangerous = safetyLevel === "dangerous";

  return (
    <div className={`surface-card p-4 mb-6 border-l-4 ${isDangerous ? "border-[var(--danger)]" : "border-[var(--warning)]"}`}>
      <div className="flex items-start gap-3">
        <ShieldAlert className={`h-6 w-6 shrink-0 ${isDangerous ? "text-[var(--danger)]" : "text-[var(--warning)]"}`} />
        <div className="min-w-0">
          <p className={`text-sm font-semibold ${isDangerous ? "text-[var(--danger)]" : "text-[var(--warning)]"} flex items-center gap-2`}>
            {isDangerous ? "Travel Risk Alert" : "Travel Caution"}
            {recommendedAction && (
              <Badge variant={recommendedAction === "avoid" ? "danger" : "warning"}>
                {recommendedAction}
              </Badge>
            )}
          </p>
          {summary && <p className="text-sm mt-1">{summary}</p>}
          {(risk.warnings ?? []).map((w, i) => (
            <p key={i} className="text-xs text-[var(--muted)] mt-1">{w}</p>
          ))}
          {threats && threats.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-medium text-[var(--muted)]">Active threats:</p>
              <ul className="mt-1 space-y-0.5">
                {threats.map((t, i) => (
                  <li key={i} className="text-xs text-[var(--muted)]">• {t}</li>
                ))}
              </ul>
            </div>
          )}
          {safeMonths && safeMonths.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-medium text-[var(--muted)]">Predicted safe periods:</p>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {safeMonths.map((m, i) => (
                  <Badge key={i} variant="success">{m}</Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function BudgetCard({ results }: { results: Record<string, AgentPlanResult> }) {
  const budget = results.budget;
  if (!budget) return null;

  const data = budget.data;
  const spent = data.spent_estimate as number | undefined;
  const total = data.budget_amount as number | undefined;
  const remaining = data.remaining as number | undefined;
  const overBudget = data.over_budget as boolean | undefined;
  const currency = data.currency as string | undefined ?? "MYR";
  const breakdown = data.breakdown as Record<string, unknown> | undefined;

  const pct = total ? Math.min(100, Math.round(((spent ?? 0) / total) * 100)) : 0;

  return (
    <section className="mb-6">
      <h3 className="flex items-center gap-2 text-lg font-semibold mb-3">
        <TrendingUp className="h-5 w-5 text-[var(--brand-500)]" />
        Budget
        <Badge variant={overBudget ? "danger" : "success"}>
          {overBudget ? "Over Budget" : "On Track"}
        </Badge>
      </h3>
      <div className="surface-card p-4 space-y-3">
        {/* Progress bar */}
        <div className="h-2 rounded-full bg-[var(--border)] overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${overBudget ? "bg-[var(--danger)]" : "bg-[var(--brand-500)]"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-[var(--muted)]">
            {currency} {(spent ?? 0).toLocaleString()} spent
          </span>
          {total != null && (
            <span className={overBudget ? "text-[var(--danger)] font-semibold" : ""}>
              {currency} {total.toLocaleString()} budget
            </span>
          )}
        </div>
        {remaining != null && (
          <p className="text-xs text-[var(--muted)]">
            {overBudget ? "Over by" : "Remaining:"} {currency} {Math.abs(remaining).toLocaleString()}
          </p>
        )}
        {/* Breakdown */}
        {breakdown && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-[var(--border)]">
            <MiniStat label="Flights" value={breakdown.flights as number} currency={currency} />
            <MiniStat label="Hotels" value={breakdown.hotels_total as number} currency={currency} />
            <MiniStat label="Activities" value={breakdown.activities as number} currency={currency} />
            <MiniStat label="Nights" value={breakdown.nights as number} />
          </div>
        )}
      </div>
    </section>
  );
}

function MiniStat({ label, value, currency }: { label: string; value: number | undefined; currency?: string }) {
  return (
    <div className="text-center">
      <p className="text-xs text-[var(--muted)]">{label}</p>
      <p className="text-sm font-semibold">
        {value != null ? `${currency ? `${currency} ` : ""}${Number(value).toLocaleString()}` : "—"}
      </p>
    </div>
  );
}

function WeatherCard({ results }: { results: Record<string, AgentPlanResult> }) {
  const weather = results.weather_risk;
  if (!weather) return null;

  const data = weather.data;
  const riskLevel = data.risk_level as string | undefined;
  const forecast = data.forecast as Array<{ date: string; high_c: number; low_c: number; precipitation_pct: number; description: string }> | undefined;
  const gdeltData = data.gdelt as { active_threats?: string[]; recent_events?: Array<{ title: string; source: string }> } | undefined;

  const riskVariant = riskLevel === "high" ? "danger" : riskLevel === "medium" ? "warning" : "success";

  return (
    <section className="mb-6">
      <h3 className="flex items-center gap-2 text-lg font-semibold mb-3">
        <Cloud className="h-5 w-5 text-[var(--brand-500)]" />
        Weather & Risk
        {riskLevel && <Badge variant={riskVariant as "success" | "warning" | "danger"}>{riskLevel} risk</Badge>}
      </h3>
      <div className="surface-card p-4">
        <p className="text-sm text-[var(--muted)] mb-3">{weather.summary}</p>
        {forecast && (
          <div className="grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-7 gap-2">
            {forecast.slice(0, 7).map((day) => (
              <div key={day.date} className="text-center p-2 rounded-[var(--r-sm)] bg-[color-mix(in_srgb,var(--brand-400)_6%,transparent)]">
                <p className="text-[0.6rem] text-[var(--muted)]">{day.date.slice(5)}</p>
                <p className="text-xs font-semibold">{day.high_c}°</p>
                <p className="text-[0.6rem] text-[var(--muted)]">{day.low_c}°</p>
                {day.precipitation_pct >= 60 && (
                  <p className="text-[0.55rem] text-[var(--warning)]">{day.precipitation_pct}%</p>
                )}
              </div>
            ))}
          </div>
        )}
        {/* GDELT events section */}
        {gdeltData && (
          <div className="mt-3 pt-3 border-t border-[var(--border)]">
            <div className="flex items-center gap-1.5 mb-2">
              <Newspaper className="h-3.5 w-3.5 text-[var(--muted)]" />
              <span className="text-xs font-medium text-[var(--muted)]">Global Events (GDELT)</span>
            </div>
            {gdeltData.active_threats && gdeltData.active_threats.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-2">
                {gdeltData.active_threats.map((t) => (
                  <Badge key={t} variant="danger">{t}</Badge>
                ))}
              </div>
            )}
            {gdeltData.recent_events?.slice(0, 3).map((ev, i) => (
              <p key={i} className="text-[0.65rem] text-[var(--muted)] leading-relaxed">
                • {ev.title} <span className="italic">({ev.source})</span>
              </p>
            ))}
            {(!gdeltData.active_threats || gdeltData.active_threats.length === 0) && (!gdeltData.recent_events || gdeltData.recent_events.length === 0) && (
              <p className="text-[0.65rem] text-[var(--success)]">No active threats detected</p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function ItinerarySection({
  results,
  setTrip,
}: {
  results: Record<string, AgentPlanResult>;
  setTrip: (trip: Record<string, AgentPlanResult>) => void;
}) {
  const [items, setItems] = useState<ItineraryItem[]>(results.itinerary?.items ?? []);
  const [refining, setRefining] = useState(false);

  if (items.length === 0) return null;

  const days = new Map<number, ItineraryItem[]>();
  for (const item of items) {
    const list = days.get(item.day_index) ?? [];
    list.push(item);
    days.set(item.day_index, list);
  }

  const persist = async (next: ItineraryItem[]) => {
    setItems(next);
    try {
      await api.post("/trip/itinerary", { items: next });
    } catch {
      toast.error("Couldn't save the new order.");
    }
  };

  // Reorder within a day, then splice that day's items back into the flat list.
  const reorderDay = (dayIndex: number, from: number, to: number) => {
    const dayItems = items.filter((i) => i.day_index === dayIndex);
    const [moved] = dayItems.splice(from, 1);
    dayItems.splice(to, 0, moved);
    let di = 0;
    const next = items.map((i) => (i.day_index === dayIndex ? dayItems[di++] : i));
    void persist(next);
  };

  const refine = async () => {
    setRefining(true);
    try {
      const res = await api.post<{ trip: Record<string, AgentPlanResult> }>(
        "/trip/itinerary/refine",
        {},
      );
      if (res.trip) {
        setTrip(res.trip);
        setItems(res.trip.itinerary?.items ?? []);
        toast.success("Your agents added ideas and realigned the schedule.");
      }
    } catch {
      toast.error("Couldn't refine the itinerary.");
    } finally {
      setRefining(false);
    }
  };

  return (
    <section className="mb-6">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="flex items-center gap-2 text-lg font-semibold">
          <Calendar className="h-5 w-5 text-[var(--brand-500)]" />
          Itinerary
          <Badge variant="brand">{items.length} items</Badge>
        </h3>
        <div className="min-w-0 flex-1" />
        <Button variant="secondary" size="sm" loading={refining} onClick={() => void refine()}>
          <Sparkles className="h-4 w-4" />
          Ask agents to add & realign
        </Button>
      </div>
      <p className="mb-3 text-xs text-[var(--muted)]">
        Use the arrows (or drag on desktop) to reorder within a day — changes save automatically.
      </p>

      <div className="space-y-4">
        {[...days.entries()]
          .sort(([a], [b]) => a - b)
          .map(([dayIndex, dayItems]) => (
            <DayItinerary
              key={dayIndex}
              dayIndex={dayIndex}
              dayItems={dayItems}
              onReorder={(from, to) => reorderDay(dayIndex, from, to)}
            />
          ))}
      </div>
    </section>
  );
}

function DayItinerary({
  dayIndex,
  dayItems,
  onReorder,
}: {
  dayIndex: number;
  dayItems: ItineraryItem[];
  onReorder: (from: number, to: number) => void;
}) {
  const [drag, setDrag] = useState<number | null>(null);
  return (
    <div>
      <h4 className="mb-2 text-sm font-semibold text-[var(--brand-500)]">Day {dayIndex}</h4>
      <ol className="space-y-1.5">
        {dayItems.map((item, idx) => (
          <li
            key={idx}
            draggable
            onDragStart={() => setDrag(idx)}
            onDragEnd={() => setDrag(null)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => {
              if (drag !== null && drag !== idx) onReorder(drag, idx);
              setDrag(null);
            }}
            className={cn(
              "surface-card flex items-start gap-2 p-3",
              drag === idx && "opacity-50",
            )}
          >
            <GripHorizontal className="mt-0.5 hidden h-4 w-4 shrink-0 cursor-grab text-[var(--muted)] active:cursor-grabbing sm:block" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{item.title}</p>
              <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
                <Badge>{item.kind}</Badge>
                {item.starts_at && (
                  <span>
                    {item.starts_at}
                    {item.ends_at ? ` – ${item.ends_at}` : ""}
                  </span>
                )}
                {item.cost_amount != null && (
                  <span className="font-medium text-[var(--brand-500)]">
                    {item.cost_currency ?? "MYR"} {Number(item.cost_amount).toLocaleString()}
                  </span>
                )}
              </div>
            </div>
            {/* Reorder controls — work on touch (HTML5 drag is desktop-only). */}
            <div className="flex shrink-0 flex-col gap-1">
              <button
                type="button"
                aria-label="Move up"
                disabled={idx === 0}
                onClick={() => onReorder(idx, idx - 1)}
                className="grid h-7 w-7 place-items-center rounded-[var(--r-sm)] text-[var(--muted)] hover:bg-[var(--bg)] disabled:opacity-30"
              >
                <ArrowUp className="h-4 w-4" />
              </button>
              <button
                type="button"
                aria-label="Move down"
                disabled={idx === dayItems.length - 1}
                onClick={() => onReorder(idx, idx + 1)}
                className="grid h-7 w-7 place-items-center rounded-[var(--r-sm)] text-[var(--muted)] hover:bg-[var(--bg)] disabled:opacity-30"
              >
                <ArrowDown className="h-4 w-4" />
              </button>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Before/after cost of a recovery.
 *
 * `comparable: false` means one side had no priced option, so there is no delta
 * to report — showing "RM 0" there would claim a free recovery that was never
 * actually measured.
 */
function CostComparison({
  detail,
  fallback,
}: {
  detail?: CostDetail;
  fallback: string;
}) {
  if (!detail) {
    return (
      <p className="text-sm text-[var(--muted)]">
        <strong>Additional cost:</strong> {fallback}
      </p>
    );
  }

  if (!detail.comparable) {
    return (
      <p className="text-sm text-[var(--warning)]">
        <strong>Cost impact:</strong> not comparable — one of the two options had
        no published price.
      </p>
    );
  }

  const delta = detail.additional_cost ?? 0;
  const tone =
    delta > 0 ? "text-[var(--danger)]" : delta < 0 ? "text-[var(--success)]" : "text-[var(--muted)]";

  return (
    <div className="grid grid-cols-3 gap-2 rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_6%,transparent)] p-3">
      <div>
        <p className="text-[0.65rem] text-[var(--muted)]">Was</p>
        <p className="text-sm font-semibold tabular-nums">
          {detail.currency} {Number(detail.original_cost ?? 0).toLocaleString()}
        </p>
      </div>
      <div>
        <p className="text-[0.65rem] text-[var(--muted)]">Now</p>
        <p className="text-sm font-semibold tabular-nums">
          {detail.currency} {Number(detail.replacement_cost ?? 0).toLocaleString()}
        </p>
      </div>
      <div>
        <p className="text-[0.65rem] text-[var(--muted)]">Difference</p>
        <p className={`text-sm font-semibold tabular-nums ${tone}`}>
          {delta > 0 ? "+" : delta < 0 ? "−" : ""}
          {detail.currency} {Math.abs(delta).toLocaleString()}
        </p>
      </div>
    </div>
  );
}

const DISRUPTION_OPTIONS = [
  { value: "flight_cancelled", label: "Flight Cancelled", icon: Plane, agent: "flight" },
  { value: "weather_alert", label: "Severe Weather", icon: Cloud, agent: "weather_risk" },
  { value: "budget_exceeded", label: "Budget Exceeded", icon: TrendingUp, agent: "budget" },
] as const;

function DisruptionSection({
  recovery,
  setRecovery,
  setRecoveryLoading,
  recoveryLoading,
}: {
  recovery: DisruptionRecovery | null;
  setRecovery: (r: DisruptionRecovery | null) => void;
  setRecoveryLoading: (l: boolean) => void;
  recoveryLoading: boolean;
}) {
  const [disruptionType, setDisruptionType] = useState<string>("flight_cancelled");

  const selected = DISRUPTION_OPTIONS.find((d) => d.value === disruptionType) ?? DISRUPTION_OPTIONS[0];

  const handleDisruption = async () => {
    setRecoveryLoading(true);
    try {
      const res = await api.post<DisruptionRecovery>("/disruption", {
        disruption_type: disruptionType,
        affected_agent: selected.agent,
      });
      setRecovery(res);
      toast.success(res.summary);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Disruption recovery failed";
      toast.error(msg);
      setRecoveryLoading(false);
    }
  };

  return (
    <section className="mt-8 mb-12">
      {!recovery ? (
        <div className="surface-card p-6 text-center">
          <AlertTriangle className="h-8 w-8 mx-auto text-[var(--warning)] mb-3" />
          <h3 className="text-lg font-semibold mb-1">Simulate a Disruption</h3>
          <p className="text-sm text-[var(--muted)] mb-4">
            Watch your agents autonomously recover: rebook flights, recalculate budget, adjust itinerary.
          </p>
          <div className="flex items-center justify-center gap-3 flex-wrap">
            <div className="w-52">
              <Select
                value={disruptionType}
                onValueChange={setDisruptionType}
                options={DISRUPTION_OPTIONS.map((d) => ({ value: d.value, label: d.label }))}
                aria-label="Disruption type"
              />
            </div>
            <Button variant="danger" onClick={handleDisruption} loading={recoveryLoading} disabled={recoveryLoading}>
              <Zap className="h-4 w-4" />
              Simulate {selected.label}
            </Button>
          </div>
        </div>
      ) : (
        <div className="surface-card p-6 border-l-4 border-[var(--success)]">
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <Badge variant="success">Recovery Complete</Badge>
            <span className="text-sm font-semibold">{recovery.summary}</span>
          </div>

          {/* Before/after, so "no additional cost" is shown to be a real
              comparison rather than an absent one. */}
          <CostComparison detail={recovery.cost_detail} fallback={recovery.additional_cost} />

          <p className="mt-3 text-sm text-[var(--muted)]">
            <strong>Agents activated:</strong>{" "}
            {recovery.agents_activated.join(" → ")}
          </p>

          {agentEntries(recovery.recovery_plan)
            .filter(([, result]) => (result.options?.length ?? 0) > 0)
            .map(([slug, result]) => (
              <div className="mt-4" key={slug}>
                <h4 className="text-sm font-medium mb-2 capitalize">
                  New {slug.replace(/_/g, " ")} options
                </h4>
                <div className="grid gap-2 sm:grid-cols-2">
                  {result.options.slice(0, 2).map((opt) => (
                    <OptionCard key={opt.id} option={opt} />
                  ))}
                </div>
              </div>
            ))}

          <div className="mt-4 flex justify-end">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setRecovery(null)}
            >
              Simulate another
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
