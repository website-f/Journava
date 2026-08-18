import { Suspense, lazy, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Briefcase, AlertTriangle, Zap, TrendingUp, Cloud, Calendar, Plane, Building2, ShieldAlert, ShieldCheck, Newspaper } from "lucide-react";
import { Button, Badge, EmptyState, LoadingOverlay, OptionCard, Select, Skeleton, confirm } from "@/components/ui";

// MapLibre is ~1MB; load it only when this page actually renders.
const TripMap = lazy(() =>
  import("@/components/ui/TripMap").then((m) => ({ default: m.TripMap })),
);
import { api } from "@/lib/api";
import { usePlanStore } from "@/stores/planStore";
import type { AgentPlanResult, CostDetail, DisruptionRecovery, ItineraryItem } from "@/stores/planStore";
import { useAgentStream } from "@/hooks/useAgentStream";
import { useActiveTrip } from "@/hooks/useActiveTrip";
import { agentEntries } from "@/lib/types";

/**
 * My Trip (spec section 3.3) — day-by-day itinerary, budget tracker, weather,
 * and the disruption simulation "money shot".
 */
export function MyTrip() {
  const { recovery, setRecovery, recoveryLoading, setRecoveryLoading } = usePlanStore();
  const { events } = useAgentStream();
  // Shared with the Research Board so both surfaces agree on the active trip.
  const { results, loading: tripLoading } = useActiveTrip();

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

      <TripHeader />
      <TripSummary results={results} />
      <RiskBanner results={results} />
      <Suspense fallback={<Skeleton className="mb-6 h-64 w-full" />}>
        <TripMap className="mb-6" />
      </Suspense>
      <BudgetCard results={results} />
      <WeatherCard results={results} />
      <ItinerarySection results={results} />
      <DisruptionSection recovery={recovery} setRecovery={setRecovery} setRecoveryLoading={setRecoveryLoading} recoveryLoading={recoveryLoading} />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Sub-components
// --------------------------------------------------------------------------- //

function TripHeader() {
  return (
    <header className="pt-2 pb-6">
      <h2 className="font-[family-name:var(--font-display)] text-2xl tracking-tight">My Trip</h2>
      <p className="mt-1 text-sm text-[var(--muted)]">
        Itinerary, budget and weather — your agents keep monitoring after checkout.
      </p>
    </header>
  );
}

function TripSummary({ results }: { results: Record<string, AgentPlanResult> }) {
  const chief = results.chief;
  const data = chief?.data ?? {};
  const destination = (data as Record<string, unknown>).destination as string | undefined;

  return (
    <div className="surface-card p-4 border-l-4 border-[var(--brand-500)] mb-6">
      <div className="flex items-center gap-3 flex-wrap">
        <h3 className="text-lg font-semibold">{destination ?? "Your Trip"}</h3>
        {chief?.summary && (
          <Badge variant="brand">{chief.summary}</Badge>
        )}
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

function ItinerarySection({ results }: { results: Record<string, AgentPlanResult> }) {
  const items = results.itinerary?.items ?? [];
  if (items.length === 0) return null;

  // Group by day
  const days = new Map<number, ItineraryItem[]>();
  for (const item of items) {
    const list = days.get(item.day_index) ?? [];
    list.push(item);
    days.set(item.day_index, list);
  }

  // Flights and hotels for the header
  const flights = results.flight?.options ?? [];
  const hotels = results.hotel?.options ?? [];

  return (
    <section className="mb-6">
      <h3 className="flex items-center gap-2 text-lg font-semibold mb-3">
        <Calendar className="h-5 w-5 text-[var(--brand-500)]" />
        Itinerary
        <Badge variant="brand">{items.length} items</Badge>
      </h3>

      {/* Flight pick */}
      {flights.length > 0 && (
        <div className="mb-4">
          <h4 className="flex items-center gap-1 text-sm font-medium mb-2">
            <Plane className="h-4 w-4 text-[var(--info)]" /> Flight
          </h4>
          <div className="grid gap-2 sm:grid-cols-2">
            {flights.slice(0, 2).map((opt) => <OptionCard key={opt.id} option={opt} />)}
          </div>
        </div>
      )}

      {/* Hotel pick */}
      {hotels.length > 0 && (
        <div className="mb-4">
          <h4 className="flex items-center gap-1 text-sm font-medium mb-2">
            <Building2 className="h-4 w-4 text-[var(--info)]" /> Hotel
          </h4>
          <div className="grid gap-2 sm:grid-cols-2">
            {hotels.slice(0, 2).map((opt) => <OptionCard key={opt.id} option={opt} />)}
          </div>
        </div>
      )}

      {/* Day-by-day */}
      <div className="space-y-4">
        {Array.from(days.entries()).map(([dayIndex, dayItems]) => (
          <div key={dayIndex}>
            <h4 className="text-sm font-semibold text-[var(--brand-500)] mb-2">Day {dayIndex}</h4>
            <ol className="space-y-1.5 border-l-2 border-[var(--border)] pl-4 ml-2">
              {dayItems.map((item, idx) => (
                <li key={idx} className="relative">
                  <span className="absolute -left-[1.25rem] top-1.5 h-2 w-2 rounded-full bg-[var(--brand-400)]" />
                  <p className="text-sm font-medium">{item.title}</p>
                  <div className="flex items-center gap-2 text-xs text-[var(--muted)] mt-0.5">
                    <Badge>{item.kind}</Badge>
                    {item.starts_at && <span>{item.starts_at}{item.ends_at ? ` – ${item.ends_at}` : ""}</span>}
                    {item.cost_amount != null && (
                      <span className="text-[var(--brand-500)] font-medium">
                        {item.cost_currency ?? "MYR"} {Number(item.cost_amount).toLocaleString()}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </section>
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
