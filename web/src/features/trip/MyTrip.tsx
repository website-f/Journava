import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Briefcase, AlertTriangle, Zap, TrendingUp, Cloud, Calendar, Plane, Building2, ShieldAlert, ShieldCheck } from "lucide-react";
import { Button, Badge, EmptyState, LoadingOverlay, OptionCard, confirm } from "@/components/ui";
import { api } from "@/lib/api";
import { usePlanStore } from "@/stores/planStore";
import type { AgentPlanResult, DisruptionRecovery, ItineraryItem } from "@/stores/planStore";
import { useAgentStream } from "@/hooks/useAgentStream";

/**
 * My Trip (spec section 3.3) — day-by-day itinerary, budget tracker, weather,
 * and the disruption simulation "money shot".
 */
export function MyTrip() {
  const { results, setResults, recovery, setRecovery, recoveryLoading, setRecoveryLoading } = usePlanStore();
  const { events } = useAgentStream();
  const [tripLoading, setTripLoading] = useState(true);

  // Load active trip on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<{ trip: Record<string, AgentPlanResult> | null }>("/trip");
        if (!cancelled && res.trip) {
          setResults(res.trip);
        }
      } catch {
        // No active trip yet
      } finally {
        if (!cancelled) setTripLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [setResults]);

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
      <div className="mx-auto w-full max-w-5xl flex items-center justify-center min-h-[60vh]">
        <p className="text-sm text-[var(--muted)]">Loading trip...</p>
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
          action={<Button asChild variant="secondary"><a href="/">Plan a trip</a></Button>}
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
  const safeMonths = data.predicted_safe_months as string[] | undefined;
  const summary = data.summary as string | undefined;

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
          <p className={`text-sm font-semibold ${isDangerous ? "text-[var(--danger)]" : "text-[var(--warning)]"}`}>
            {isDangerous ? "Travel Risk Alert" : "Travel Caution"}
          </p>
          {summary && <p className="text-sm mt-1">{summary}</p>}
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

  const riskVariant = riskLevel === "high" ? "danger" : riskLevel === "medium" ? "warning" : "success";

  return (
    <section className="mb-6">
      <h3 className="flex items-center gap-2 text-lg font-semibold mb-3">
        <Cloud className="h-5 w-5 text-[var(--brand-500)]" />
        Weather
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
  const handleDisruption = async () => {
    setRecoveryLoading(true);
    try {
      const res = await api.post<DisruptionRecovery>("/disruption", {
        disruption_type: "flight_cancelled",
        affected_agent: "flight",
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
          <Button variant="danger" onClick={handleDisruption} loading={recoveryLoading} disabled={recoveryLoading}>
            <Zap className="h-4 w-4" />
            Simulate Flight Cancelled
          </Button>
        </div>
      ) : (
        <div className="surface-card p-6 border-l-4 border-[var(--success)]">
          <div className="flex items-center gap-2 mb-3">
            <Badge variant="success">Recovery Complete</Badge>
            <span className="text-sm font-semibold">{recovery.summary}</span>
          </div>
          <div className="space-y-2 text-sm text-[var(--muted)]">
            <p><strong>Additional cost:</strong> {recovery.additional_cost}</p>
            <p><strong>Agents activated:</strong> {recovery.agents_activated.join(" → ")}</p>
          </div>
          {/* Show new flight options from recovery */}
          {recovery.recovery_plan.flight?.options?.length > 0 && (
            <div className="mt-4">
              <h4 className="text-sm font-medium mb-2">New Flight Options</h4>
              <div className="grid gap-2 sm:grid-cols-2">
                {recovery.recovery_plan.flight.options.slice(0, 2).map((opt) => (
                  <OptionCard key={opt.id} option={opt} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
