import { Suspense, lazy, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Briefcase, AlertTriangle, Zap, TrendingUp, Cloud, Calendar, Clock, GripHorizontal, Plane, ShieldAlert, ShieldCheck, Sparkles, Trash2, Newspaper, ArrowUp, ArrowDown, CheckCircle2, Check, Plus, Compass, Utensils, Copy, Download } from "@/components/ui/icons";
import { Button, Badge, EmptyState, LoadingOverlay, OptionCard, Select, Skeleton, confirm } from "@/components/ui";
import { Rail } from "@/components/layout/Page";
import { Switch } from "@/components/ui/Switch";
import { Money } from "@/components/ui/Money";
import { cn } from "@/lib/cn";

// MapLibre is ~1MB; load it only when this page actually renders.
const TripMap = lazy(() =>
  import("@/components/ui/TripMap").then((m) => ({ default: m.TripMap })),
);
import { api, API_BASE } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { PriceWatchCard } from "./PriceWatchCard";
import { ExpenseSplitCard } from "./ExpenseSplitCard";
import { useChecklist } from "@/hooks/useChecklist";
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
      <TodayCard results={results} />
      <PlanReadinessNote results={results} />
      <RiskBanner results={results} />
      <Suspense fallback={<Skeleton className="mb-6 h-64 w-full" />}>
        <TripMap className="mb-6" />
      </Suspense>
      <BudgetCard results={results} />
      <WeatherCard results={results} />
      <CompleteItineraryCard results={results} setTrip={setTrip} />
      <BudgetOptimizerCard results={results} setTrip={setTrip} />
      <ItinerarySection results={results} setTrip={setTrip} />
      <BackupRail results={results} setTrip={setTrip} />
      <ExpenseSplitCard results={results} />
      <TripStoryCard results={results} />
      {/* The full plan — flights, stays, food, places, visa, insurance — so the
          saved trip shows everything the agents produced, not just the summary. */}
      <div className="mt-8">
        <TripExtraPanels results={results as PlanResults} />
      </div>
      <LocalIntelCard />
      <FlightWatchCard />
      <PriceWatchCard />
      <ItineraryGraphCard />
      <GuardianCard />
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
// Itinerary as a dependency graph — cascade a delay + settle the fare diff
// --------------------------------------------------------------------------- //

type ReplanNode = { id: string; kind: string; day: number; title: string; starts_at?: string; conflict?: string | null };
type ReplanResult = {
  error?: string;
  graph: { nodes: ReplanNode[] };
  impacted: ReplanNode[];
  rebook: { summary: string; additional_cost: string };
  settlement: { direction: string; fare_delta: number | null; currency: string; mode?: string };
};

function LegDot({ kind }: { kind: string }) {
  const label: Record<string, string> = { flight: "✈", hotel: "🏨", activity: "◆", meal: "🍽", transport: "🚌" };
  return <span className="w-5 shrink-0 text-center text-xs">{label[kind] ?? "◆"}</span>;
}

function ItineraryGraphCard() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ReplanResult | null>(null);

  const run = async () => {
    setLoading(true);
    try {
      const r = await api.post<ReplanResult>("/itinerary/replan", { event_type: "flight_delayed", delay_minutes: 200, persist: false });
      if (r.error) toast.info(r.error);
      else {
        setResult(r);
        toast.success(`Re-planned — ${r.impacted.length} leg(s) fixed`);
      }
    } catch {
      toast.error("Couldn't re-plan the itinerary.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="mt-8">
      <div className="surface-card p-5">
        <div className="mb-1 flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-[var(--brand-500)]" />
          <h3 className="text-base font-semibold">Itinerary dependency graph</h3>
        </div>
        <p className="mb-4 text-sm text-[var(--muted)]">
          Your legs depend on each other. If a flight slips, Journava cascades the shift, re-plans every
          broken leg, and settles the fare difference automatically.
        </p>
        <Button variant="secondary" onClick={run} loading={loading} disabled={loading}>
          <Zap className="h-4 w-4" /> Simulate a 200-min delay &amp; auto-replan
        </Button>

        {result && (
          <div className="mt-5 space-y-4">
            <div className="rounded-[var(--r-md)] bg-[var(--bg)] p-3 text-sm">
              <strong>Cascade:</strong> {result.rebook.summary}
              {result.settlement.fare_delta != null && (
                <>
                  {" "}· fare{" "}
                  {result.settlement.direction === "refund"
                    ? "refund"
                    : result.settlement.direction === "upcharge"
                      ? "top-up"
                      : "unchanged"}{" "}
                  {result.settlement.currency} {Math.abs(result.settlement.fare_delta).toLocaleString()}
                  {result.settlement.mode ? ` (${result.settlement.mode})` : ""}
                </>
              )}
            </div>
            <div className="space-y-1">
              {result.graph.nodes.map((n) => {
                const broken = result.impacted.some((i) => i.id === n.id);
                return (
                  <div
                    key={n.id}
                    className={cn(
                      "flex items-center gap-2 rounded-[var(--r-md)] px-3 py-1.5 text-sm",
                      broken ? "bg-[color-mix(in_srgb,var(--warning)_12%,transparent)]" : "bg-[var(--bg)]",
                    )}
                  >
                    <LegDot kind={n.kind} />
                    <span className="w-8 shrink-0 text-xs text-[var(--muted)]">D{n.day}</span>
                    <span className="w-14 shrink-0 text-xs tabular-nums text-[var(--muted)]">{n.starts_at ?? "—"}</span>
                    <span className="min-w-0 flex-1 truncate">{n.title}</span>
                    {n.conflict && <Badge variant="warning">{n.conflict.replace(/_/g, " ")}</Badge>}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Local intelligence — crowd levels + best times + social do's / don'ts
// --------------------------------------------------------------------------- //

type LocalIntel = {
  places: { name: string; crowd_level: string; best_time: string; note: string }[];
  recommendations: string[];
  donts: string[];
  sourced: boolean;
};

function LocalIntelCard() {
  const [loading, setLoading] = useState(false);
  const [intel, setIntel] = useState<LocalIntel | null>(null);

  const run = async () => {
    setLoading(true);
    try {
      setIntel(await api.post<LocalIntel>("/trip/local-intel", {}));
    } catch {
      toast.error("Couldn't gather local intelligence.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="mt-8">
      <div className="surface-card p-5">
        <div className="mb-1 flex items-center gap-2">
          <Newspaper className="h-5 w-5 text-[var(--brand-500)]" />
          <h3 className="text-base font-semibold">Local intelligence</h3>
          {intel && <Badge variant={intel.sourced ? "success" : "brand"}>{intel.sourced ? "from live sources" : "estimate"}</Badge>}
        </div>
        <p className="mb-4 text-sm text-[var(--muted)]">
          How busy each place gets and when to go, plus what locals recommend — and what to avoid.
        </p>
        <Button variant="secondary" onClick={run} loading={loading} disabled={loading}>
          <Sparkles className="h-4 w-4" /> Check crowds &amp; social tips
        </Button>

        {intel && (
          <div className="mt-5 space-y-4">
            {!!intel.places.length && (
              <div>
                <p className="mb-2 text-[0.65rem] font-semibold uppercase tracking-wide text-[var(--muted)]">
                  Crowd heatmap · best time to go
                </p>
                <div className="space-y-2">
                  {intel.places.map((p, i) => {
                    const lvl = (p.crowd_level || "").toLowerCase();
                    const fill = lvl === "high" ? 100 : lvl === "medium" ? 62 : lvl === "low" ? 28 : 45;
                    const color =
                      lvl === "high"
                        ? "var(--danger,#dc2626)"
                        : lvl === "medium"
                          ? "var(--warning)"
                          : "var(--success)";
                    return (
                      <div key={i} className="flex items-center gap-2.5">
                        <span className="min-w-0 flex-1 truncate text-xs font-medium">{p.name}</span>
                        <div
                          className="h-2 w-16 shrink-0 overflow-hidden rounded-full bg-[var(--border)] sm:w-24"
                          title={`${p.crowd_level} crowds`}
                        >
                          <div className="h-full rounded-full transition-all" style={{ width: `${fill}%`, background: color }} />
                        </div>
                        <span className="w-12 shrink-0 text-right text-[0.6rem] uppercase capitalize" style={{ color }}>
                          {p.crowd_level}
                        </span>
                        {p.best_time && (
                          <span className="hidden w-24 shrink-0 truncate text-[0.65rem] text-[var(--muted)] sm:inline" title={p.best_time}>
                            🕑 {p.best_time}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
                <p className="mt-2 text-[0.6rem] text-[var(--muted)]">
                  Shorter green bars are quieter — visit at the “best time” to dodge the crowd.
                </p>
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              {!!intel.recommendations.length && (
                <div className="rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--success)_8%,transparent)] p-3">
                  <p className="mb-1 text-xs font-semibold text-[var(--success)]">Recommended</p>
                  {intel.recommendations.map((r, i) => <p key={i} className="text-xs text-[var(--muted)]">✓ {r}</p>)}
                </div>
              )}
              {!!intel.donts.length && (
                <div className="rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--warning)_8%,transparent)] p-3">
                  <p className="mb-1 text-xs font-semibold text-[var(--warning)]">Avoid</p>
                  {intel.donts.map((d, i) => <p key={i} className="text-xs text-[var(--muted)]">✕ {d}</p>)}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Predictive guardian — forecast a disruption before it happens + act
// --------------------------------------------------------------------------- //

type GuardianReport = {
  error?: string;
  destination: string;
  risk_level: string;
  disruption_probability_pct: number;
  signals: string[];
  predicted: { event: string; likelihood: string; window: string }[];
  actions: { action: string; status: string; detail: string }[];
  overnight_feed: { time: string; note: string }[];
  armed: boolean;
};

function GuardianCard() {
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<GuardianReport | null>(null);

  const scan = async () => {
    setLoading(true);
    try {
      const r = await api.post<GuardianReport>("/guardian/scan", { horizon_days: 4 });
      if (r.error) toast.info(r.error);
      else setReport(r);
    } catch {
      toast.error("Guardian scan failed.");
    } finally {
      setLoading(false);
    }
  };

  const riskTone: Record<string, string> = {
    low: "text-[var(--success)]",
    medium: "text-[var(--warning)]",
    high: "text-[var(--danger,#dc2626)]",
  };
  const statusTone: Record<string, "success" | "warning" | "brand"> = { done: "success", watching: "brand", recommended: "warning" };

  return (
    <section className="mt-8">
      <div className="surface-card p-5">
        <div className="mb-1 flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-[var(--brand-500)]" />
          <h3 className="text-base font-semibold">Predictive guardian</h3>
          {report?.armed && <Badge variant="success">armed</Badge>}
        </div>
        <p className="mb-4 text-sm text-[var(--muted)]">
          Journava forecasts a disruption <strong>before it happens</strong> and acts on your behalf — then
          reports what it did while you slept.
        </p>
        <Button variant="secondary" onClick={scan} loading={loading} disabled={loading}>
          <Sparkles className="h-4 w-4" /> Run guardian scan
        </Button>

        {report && (
          <div className="mt-5 space-y-4">
            <div className="flex flex-wrap items-baseline gap-x-4">
              <span className={cn("text-2xl font-bold capitalize", riskTone[report.risk_level] ?? "")}>{report.risk_level} risk</span>
              <span className="text-sm text-[var(--muted)]">~{report.disruption_probability_pct}% chance of disruption · {report.destination}</span>
            </div>
            {!!report.signals.length && (
              <p className="text-sm text-[var(--muted)]"><strong className="text-[var(--text)]">Signals:</strong> {report.signals.join(" · ")}</p>
            )}
            {!!report.predicted.length && (
              <div>
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">Predicted</p>
                <div className="space-y-1">
                  {report.predicted.map((p, i) => (
                    <div key={i} className="flex items-center gap-2 text-sm">
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-[var(--warning)]" />
                      <span className="flex-1">{p.event}</span>
                      <span className="text-xs text-[var(--muted)]">{p.likelihood} · {p.window}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {!!report.actions.length && (
              <div>
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">Pre-emptive actions</p>
                <div className="space-y-1">
                  {report.actions.map((a, i) => (
                    <div key={i} className="flex items-center gap-2 text-sm">
                      <Badge variant={statusTone[a.status] ?? "brand"}>{a.status}</Badge>
                      <span className="flex-1">{a.action}</span>
                      <span className="hidden text-xs text-[var(--muted)] sm:inline">{a.detail}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {!!report.overnight_feed.length && (
              <div className="rounded-[var(--r-md)] bg-[var(--bg)] p-3">
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">While you slept</p>
                {report.overnight_feed.map((f, i) => (
                  <p key={i} className="text-xs text-[var(--muted)]"><span className="font-semibold tabular-nums text-[var(--brand-600)]">{f.time}</span> · {f.note}</p>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// Complete-your-itinerary place picker + plan readiness
// --------------------------------------------------------------------------- //

type Suggestion = {
  id?: string;
  title: string;
  kind?: string;
  price_amount?: number | null;
  price_currency?: string | null;
  booking_url?: string | null;
  source_url?: string | null;
  source?: string;
  reasoning?: string | null;
  halal_confidence?: string | null;
  raw?: { rating?: number | string | null };
};

const _key = (t?: string) => (t ?? "").trim().toLowerCase();

/**
 * The interactive itinerary designer. The agents suggest far more places than a
 * short trip can fit; here the traveller taps the ones they want, and we
 * schedule them into full days — everything they leave out is kept as a backup
 * shortlist they can pull in later (see BackupRail).
 */
function CompleteItineraryCard({
  results,
  setTrip,
}: {
  results: Record<string, AgentPlanResult>;
  setTrip: (trip: Record<string, AgentPlanResult>) => void;
}) {
  // Merge everything the agents suggested (research + recommendation), deduped.
  const suggestions = useMemo(() => {
    const seen = new Set<string>();
    const out: Suggestion[] = [];
    for (const o of [
      ...((results.research?.options ?? []) as Suggestion[]),
      ...((results.recommendation?.options ?? []) as Suggestion[]),
    ]) {
      if (o.kind !== "activity" && o.kind !== "restaurant") continue;
      const k = _key(o.title);
      if (!k || seen.has(k)) continue;
      seen.add(k);
      out.push(o);
    }
    return out;
  }, [results]);

  const scheduled = useMemo(
    () => new Set((results.itinerary?.items ?? []).map((i) => _key(i.title))),
    [results],
  );
  const [days, setDays] = useState(() => {
    const items = results.itinerary?.items ?? [];
    return items.length ? Math.max(...items.map((i) => Number(i.day_index) || 1)) : 3;
  });
  // Pre-seed the selection from whatever is already scheduled, so the picker
  // reflects the current plan instead of starting blank.
  const [picked, setPicked] = useState<Set<string>>(
    () => new Set(suggestions.filter((s) => scheduled.has(_key(s.title))).map((s) => s.title)),
  );
  const [busy, setBusy] = useState(false);
  if (suggestions.length === 0) return null;

  const toggle = (t: string) =>
    setPicked((s) => {
      const n = new Set(s);
      if (n.has(t)) n.delete(t);
      else n.add(t);
      return n;
    });

  const fit = days * 3;
  const build = async () => {
    const picks = suggestions
      .filter((s) => picked.has(s.title))
      .map((s) => ({
        id: s.id,
        title: s.title,
        kind: s.kind,
        price_amount: s.price_amount,
        price_currency: s.price_currency,
        booking_url: s.booking_url ?? s.source_url,
        source: s.source,
        reasoning: s.reasoning,
        rating: s.raw?.rating,
      }));
    if (!picks.length) return toast.info("Pick a few places first.");
    setBusy(true);
    try {
      const r = await api.post<{ trip: Record<string, AgentPlanResult> }>("/trip/itinerary/build", { days, picks });
      setTrip(r.trip);
      toast.success(`Scheduled ${picks.length} place(s) across ${days} days — the rest are in your backup.`);
    } catch {
      toast.error("Couldn't build the itinerary.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="surface-card mb-6 p-5">
      <div className="mb-1 flex items-center gap-2">
        <Sparkles className="h-5 w-5 text-[var(--brand-500)]" />
        <h3 className="text-base font-semibold">Design your days</h3>
      </div>
      <p className="mb-3 text-sm text-[var(--muted)]">
        Your agents found <strong className="text-[var(--text)]">{suggestions.length}</strong> places. Tap the ones
        you want — we'll schedule them across full days and keep the rest as backup you can swap in anytime.
      </p>

      {/* Selectable place cards */}
      <div className="grid max-h-80 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
        {suggestions.map((s) => {
          const on = picked.has(s.title);
          const isFood = s.kind === "restaurant";
          const Icon = isFood ? Utensils : Compass;
          const rating = s.raw?.rating;
          return (
            <button
              key={s.title}
              onClick={() => toggle(s.title)}
              aria-pressed={on}
              className={cn(
                "flex items-start gap-2.5 rounded-[var(--r-md)] border p-2.5 text-left transition-all",
                on
                  ? "border-[var(--brand-500)] bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)] ring-1 ring-[var(--brand-500)]"
                  : "border-[var(--border)] hover:border-[var(--brand-400)]",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-[var(--r-sm)] border transition-colors",
                  on ? "border-[var(--brand-500)] bg-[var(--brand-500)] text-white" : "border-[var(--border)]",
                )}
              >
                {on && <Check className="h-3.5 w-3.5" weight="bold" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <Icon className="h-3.5 w-3.5 shrink-0 text-[var(--brand-500)]" />
                  <span className="min-w-0 truncate text-xs font-medium">{s.title}</span>
                </span>
                <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.65rem] text-[var(--muted)]">
                  {s.price_amount != null && (
                    <span className="font-medium text-[var(--brand-500)]">
                      <Money amount={s.price_amount} currency={s.price_currency ?? "MYR"} />
                    </span>
                  )}
                  {rating != null && rating !== "" && <span className="text-[var(--accent)]">★ {rating}</span>}
                  {isFood && s.halal_confidence && <span className="capitalize">{String(s.halal_confidence).replace(/_/g, " ")}</span>}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <div className="w-28">
          <Select
            value={String(days)}
            onValueChange={(v) => setDays(Number(v))}
            options={[2, 3, 4, 5, 6, 7].map((n) => ({ value: String(n), label: `${n} days` }))}
            aria-label="days"
          />
        </div>
        <span className="text-xs text-[var(--muted)]">
          <strong className={cn(picked.size > fit ? "text-[var(--warning)]" : "text-[var(--text)]")}>{picked.size}</strong>{" "}
          selected · a {days}-day trip fits ~{fit}
          {picked.size > fit && " (we'll keep the best, rest → backup)"}
        </span>
        <Button className="ml-auto" onClick={build} loading={busy} disabled={!picked.size}>
          <Sparkles className="h-4 w-4" /> Build my {days}-day plan
        </Button>
      </div>
    </section>
  );
}

/**
 * Backup shortlist — the suggestions that didn't make the schedule. Each can be
 * pulled straight into the plan (instant, no rebuild); a scheduled place bumped
 * out lands back here. This is what makes the plan feel alive and reversible.
 */
function BackupRail({
  results,
  setTrip,
}: {
  results: Record<string, AgentPlanResult>;
  setTrip: (trip: Record<string, AgentPlanResult>) => void;
}) {
  const backup = ((results.itinerary as { backup?: Suggestion[] } | undefined)?.backup ?? []) as Suggestion[];
  const [busy, setBusy] = useState<string | null>(null);
  if (!backup.length) return null;

  const add = async (title: string) => {
    setBusy(title);
    try {
      const r = await api.post<{ trip: Record<string, AgentPlanResult> }>("/trip/itinerary/pick", { title, action: "add" });
      setTrip(r.trip);
      toast.success(`Added “${title}” to your plan.`);
    } catch {
      toast.error("Couldn't add that to the plan.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="surface-card mb-6 p-5">
      <div className="mb-1 flex items-center gap-2">
        <Briefcase className="h-5 w-5 text-[var(--accent)]" />
        <h3 className="text-base font-semibold">Backup ideas</h3>
        <span className="rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--accent)_16%,transparent)] px-2 py-0.5 text-[0.65rem] font-semibold text-[var(--accent)]">
          {backup.length}
        </span>
      </div>
      <p className="mb-3 text-sm text-[var(--muted)]">
        Great picks that didn't fit — tap ＋ to slot any into your plan.
      </p>
      <Rail card="13.5rem" cols={2} colsLg={3} pad="1.25rem" aria-label="Backup ideas">
        {backup.map((b) => {
          const isFood = b.kind === "restaurant";
          const Icon = isFood ? Utensils : Compass;
          return (
            <div key={b.title} className="flex flex-col rounded-[var(--r-md)] border border-[var(--border)] p-3">
              <span className="flex items-center gap-1.5">
                <Icon className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" />
                <span className="min-w-0 flex-1 truncate text-xs font-medium">{b.title}</span>
              </span>
              {(b.reasoning || b.price_amount != null) && (
                <span className="mt-1 line-clamp-2 flex-1 text-[0.65rem] text-[var(--muted)]">
                  {b.price_amount != null && (
                    <>
                      <Money amount={b.price_amount} currency={b.price_currency ?? "MYR"} />
                      {b.reasoning ? " · " : ""}
                    </>
                  )}
                  {b.reasoning}
                </span>
              )}
              <button
                onClick={() => void add(b.title)}
                disabled={busy === b.title}
                className="mt-2 inline-flex items-center justify-center gap-1 rounded-[var(--r-md)] border border-[var(--brand-400)] px-2.5 py-1.5 text-xs font-medium text-[var(--brand-600)] transition-colors hover:bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)] disabled:opacity-60"
              >
                <Plus className="h-3.5 w-3.5" /> Add to plan
              </button>
            </div>
          );
        })}
      </Rail>
    </section>
  );
}

type TripStory = {
  title?: string;
  story?: string;
  captions?: { platform: string; text: string }[];
  hashtags?: string[];
  destination?: string;
};

/**
 * Generative trip content (hackathon direction 08). Turns the real plan into a
 * shareable story + ready-to-post captions + hashtags — the inverse of the
 * social-link ingestion, grounded in the actual destination/itinerary.
 */
function TripStoryCard({ results }: { results: Record<string, AgentPlanResult> }) {
  const [story, setStory] = useState<TripStory | null>(null);
  const [busy, setBusy] = useState(false);
  const hasTrip = Boolean((results.chief?.data as { destination?: string } | undefined)?.destination);
  if (!hasTrip) return null;

  const generate = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ content?: TripStory; error?: string }>("/content/story", { results });
      if (r.content?.story) setStory(r.content);
      else toast.error(r.error || "Couldn't write the story.");
    } catch {
      toast.error("Couldn't write the story right now.");
    } finally {
      setBusy(false);
    }
  };

  const copy = (text: string) => {
    navigator.clipboard?.writeText(text).then(
      () => toast.success("Copied to clipboard."),
      () => toast.error("Couldn't copy."),
    );
  };

  return (
    <section className="surface-card mb-6 p-5">
      <div className="mb-1 flex items-center gap-2">
        <Sparkles className="h-5 w-5 text-[var(--accent)]" />
        <h3 className="text-base font-semibold">Share your trip</h3>
      </div>
      <p className="mb-3 text-sm text-[var(--muted)]">
        Let the agents write a shareable story and ready-to-post captions from your actual plan.
      </p>

      {!story ? (
        <Button variant="secondary" size="sm" loading={busy} onClick={() => void generate()}>
          <Sparkles className="h-4 w-4" /> Generate a story
        </Button>
      ) : (
        <div className="space-y-3">
          <div className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] p-3">
            <div className="mb-1 flex items-center justify-between gap-2">
              <p className="font-[family-name:var(--font-display)] text-sm font-semibold">{story.title}</p>
              <button
                onClick={() => copy(`${story.title}\n\n${story.story}`)}
                className="inline-flex items-center gap-1 text-[0.65rem] text-[var(--brand-500)] hover:underline"
              >
                <Copy className="h-3 w-3" /> Copy
              </button>
            </div>
            <p className="whitespace-pre-line text-xs leading-relaxed text-[var(--muted)]">{story.story}</p>
          </div>

          {(story.captions ?? []).map((c) => (
            <div key={c.platform} className="rounded-[var(--r-md)] border border-[var(--border)] p-3">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[0.6rem] font-semibold uppercase tracking-wide text-[var(--accent)]">{c.platform}</span>
                <button
                  onClick={() => copy(`${c.text}\n\n${(story.hashtags ?? []).join(" ")}`)}
                  className="inline-flex items-center gap-1 text-[0.65rem] text-[var(--brand-500)] hover:underline"
                >
                  <Copy className="h-3 w-3" /> Copy
                </button>
              </div>
              <p className="text-xs">{c.text}</p>
            </div>
          ))}

          {(story.hashtags ?? []).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {story.hashtags!.map((h) => (
                <span key={h} className="rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)] px-2 py-0.5 text-[0.65rem] text-[var(--brand-600)]">
                  {h}
                </span>
              ))}
            </div>
          )}

          <button onClick={() => void generate()} disabled={busy} className="text-xs text-[var(--muted)] hover:underline">
            Regenerate
          </button>
        </div>
      )}
    </section>
  );
}

type OptimizeResult = {
  currency: string;
  budget: number;
  before: number;
  after: number;
  within_budget: boolean;
  breakdown: { flight: number; hotel: number; activities: number };
  recommended: { flight_from_pp: number | null; hotel_per_night: number | null; nights: number; travellers: number };
  trimmed: { title: string; saved: number }[];
  trip?: Record<string, AgentPlanResult>;
};

/**
 * Budget auto-optimizer — "fit my trip to RM X". An agent prices the trip
 * (cheapest flight x pax + cheapest stay x nights + scheduled activities) and,
 * if over, trims the priciest activities to backup until it fits — reversibly.
 */
function BudgetOptimizerCard({
  results,
  setTrip,
}: {
  results: Record<string, AgentPlanResult>;
  setTrip: (trip: Record<string, AgentPlanResult>) => void;
}) {
  const chief = (results.chief?.data ?? {}) as { destination?: string; budget_amount?: number; budget_currency?: string };
  const [budget, setBudget] = useState<string>(chief.budget_amount ? String(chief.budget_amount) : "");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<OptimizeResult | null>(null);
  if (!chief.destination) return null;
  const ccy = chief.budget_currency || "MYR";

  const run = async () => {
    const amt = Number(budget);
    if (!amt || amt <= 0) return toast.info("Enter a target budget first.");
    setBusy(true);
    try {
      const r = await api.post<OptimizeResult>("/trip/optimize", { budget_amount: amt, currency: ccy });
      setRes(r);
      if (r.trip) setTrip(r.trip);
      toast[r.within_budget ? "success" : "info"](
        r.within_budget ? "Your trip fits the budget." : "Trimmed to get as close as possible.",
      );
    } catch {
      toast.error("Couldn't optimize the trip.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="surface-card mb-6 p-5">
      <div className="mb-1 flex items-center gap-2">
        <TrendingUp className="h-5 w-5 text-[var(--brand-500)]" />
        <h3 className="text-base font-semibold">Fit to budget</h3>
      </div>
      <p className="mb-3 text-sm text-[var(--muted)]">
        Set a target and your agents price the trip and trim to fit — trimmed picks go to backup.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5 rounded-[var(--r-md)] border border-[var(--border)] px-3 py-1.5">
          <span className="text-xs text-[var(--muted)]">{ccy}</span>
          <input
            className="w-24 bg-transparent text-sm outline-none"
            inputMode="numeric"
            placeholder="6000"
            value={budget}
            onChange={(e) => setBudget(e.target.value.replace(/[^\d.]/g, ""))}
            aria-label="Target budget"
          />
        </div>
        <Button size="sm" loading={busy} onClick={() => void run()}>
          <TrendingUp className="h-4 w-4" /> Fit my trip
        </Button>
      </div>

      {res && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="text-[var(--muted)]">
              {ccy} {res.before.toLocaleString()} <span className="mx-1">→</span>
              <strong className={res.within_budget ? "text-[var(--success)]" : "text-[var(--warning)]"}>
                {ccy} {res.after.toLocaleString()}
              </strong>
            </span>
            <span
              className={cn(
                "rounded-[var(--r-pill)] px-2 py-0.5 text-[0.6rem] font-semibold uppercase",
                res.within_budget
                  ? "bg-[color-mix(in_srgb,var(--success)_16%,transparent)] text-[var(--success)]"
                  : "bg-[color-mix(in_srgb,var(--warning)_16%,transparent)] text-[var(--warning)]",
              )}
            >
              {res.within_budget ? "within budget" : "closest possible"}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {(["flight", "hotel", "activities"] as const).map((k) => (
              <div key={k} className="rounded-[var(--r-sm)] bg-[var(--bg)] p-2">
                <p className="text-[0.6rem] uppercase tracking-wide text-[var(--muted)]">{k}</p>
                <p className="text-xs font-semibold">{ccy} {res.breakdown[k].toLocaleString()}</p>
              </div>
            ))}
          </div>
          <p className="text-[0.65rem] text-[var(--muted)]">
            Based on cheapest flight ×{res.recommended.travellers} + stay ×{res.recommended.nights} nights + activities.
            {res.trimmed.length > 0 && ` Trimmed ${res.trimmed.length} to backup: ${res.trimmed.map((t) => t.title).join(", ")}.`}
          </p>
        </div>
      )}
    </section>
  );
}

/** A one-line readiness banner: what's in the plan and what still needs a choice. */
function PlanReadinessNote({ results }: { results: Record<string, AgentPlanResult> }) {
  const flights = results.flight?.options ?? [];
  const bySource = (src: string) => flights.filter((o) => (o.source ?? o.raw?.source) === src).length;
  const atlas = bySource("atlas");
  const research = bySource("camofox");
  const places = (results.research?.options ?? []).filter((o) => o.kind === "activity" || o.kind === "restaurant").length;
  const scheduled = results.itinerary?.items?.length ?? 0;
  if (!flights.length && !places) return null;
  return (
    <div className="mb-6 flex flex-wrap items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-4 py-2.5 text-xs">
      {flights.length > 0 && (
        <span className="flex items-center gap-1.5">
          <Plane className="h-3.5 w-3.5 text-[var(--brand-500)]" />
          {flights.length} flight options ({atlas} Atlas · {research} research) — <strong>outbound &amp; return not chosen yet</strong>
        </span>
      )}
      {places > 0 && (
        <span className="flex items-center gap-1.5 text-[var(--muted)]">
          · {places} places found · {scheduled ? `${scheduled} scheduled` : "none scheduled — pick below"}
        </span>
      )}
    </div>
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
  const [sharing, setSharing] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const share = async () => {
    setSharing(true);
    try {
      const r = await api.post<{ url: string }>("/trip/share", { results });
      const url = r.url.startsWith("http") ? r.url : `${window.location.origin}${r.url}`;
      await navigator.clipboard?.writeText(url).catch(() => {});
      toast.success("Public link copied — anyone can open this plan.");
    } catch {
      toast.error("Couldn't create a share link.");
    } finally {
      setSharing(false);
    }
  };

  // Offline pass — download a self-contained PDF that opens with no signal.
  const downloadOffline = async () => {
    setDownloading(true);
    try {
      const token = getAccessToken();
      const res = await fetch(`${API_BASE}/trip/export/pdf`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ results }),
      });
      if (!res.ok) throw new Error("export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "journava-trip.pdf";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Trip saved for offline — open the PDF anytime, no signal needed.");
    } catch {
      toast.error("Couldn't prepare the offline pass.");
    } finally {
      setDownloading(false);
    }
  };

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
        {results && (
          <Button variant="secondary" size="sm" loading={sharing} onClick={() => void share()}>
            <Copy className="h-4 w-4" />
            Share
          </Button>
        )}
        {results && (
          <Button variant="secondary" size="sm" loading={downloading} onClick={() => void downloadOffline()}>
            <Download className="h-4 w-4" />
            Offline
          </Button>
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

/**
 * Today companion — while a trip is in progress, surface *today's* plan at the
 * top with an "up next" highlight. The on-screen counterpart to the daily
 * "what to do today" push. Renders nothing outside the travel window.
 */
function TodayCard({ results }: { results: Record<string, AgentPlanResult> }) {
  const chief = (results.chief?.data as { destination?: string; start_date?: string } | undefined) ?? {};
  const items = (results.itinerary?.items ?? []) as ItineraryItem[];
  if (!chief.start_date || items.length === 0) return null;
  const start = new Date(`${chief.start_date}T00:00:00`);
  if (Number.isNaN(start.getTime())) return null;

  const now = new Date();
  const today0 = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dayN = Math.floor((today0.getTime() - start.getTime()) / 86_400_000) + 1;
  const maxDay = Math.max(...items.map((i) => Number(i.day_index) || 1));
  if (dayN < 1 || dayN > maxDay) return null; // trip not in progress today

  const todays = items
    .filter((i) => Number(i.day_index) === dayN)
    .sort((a, b) => String(a.starts_at ?? "").localeCompare(String(b.starts_at ?? "")));
  if (todays.length === 0) return null;

  const hhmm = now.toTimeString().slice(0, 5);
  const nextIdx = todays.findIndex((i) => String(i.starts_at ?? "99:99") >= hhmm);
  const dest = chief.destination ?? "your trip";

  return (
    <section className="mb-6">
      <div className="surface-card border-l-4 border-[var(--brand-500)] p-5">
        <div className="mb-3 flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-[var(--brand-500)]" />
          <h3 className="text-base font-semibold">
            Today · Day {dayN} in {dest}
          </h3>
        </div>
        <ol className="space-y-1.5">
          {todays.map((it, i) => (
            <li
              key={i}
              className={cn(
                "flex items-center gap-2.5 rounded-[var(--r-md)] px-3 py-2 text-sm",
                i === nextIdx
                  ? "bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)] ring-1 ring-[var(--brand-500)]/30"
                  : "bg-[var(--bg)]",
              )}
            >
              <span className="w-12 shrink-0 text-xs tabular-nums text-[var(--muted)]">{it.starts_at ?? "—"}</span>
              <span className="min-w-0 flex-1 truncate">{it.title}</span>
              {i === nextIdx && <Badge variant="brand">Up next</Badge>}
            </li>
          ))}
        </ol>
      </div>
    </section>
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

  // Stable per-trip key for the offline checklist.
  const chief = (results.chief?.data as { destination?: string; start_date?: string } | undefined) ?? {};
  const tripKey = `${chief.destination ?? "trip"}:${chief.start_date ?? ""}`;
  const { toggle, isDone } = useChecklist(tripKey);

  if (items.length === 0) return null;

  const days = new Map<number, ItineraryItem[]>();
  for (const item of items) {
    const list = days.get(item.day_index) ?? [];
    list.push(item);
    days.set(item.day_index, list);
  }

  const itemKey = (item: ItineraryItem) => `${item.day_index}:${item.title}`;
  const doneCount = items.filter((i) => isDone(itemKey(i))).length;
  const pct = items.length ? Math.round((doneCount / items.length) * 100) : 0;

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

  // Bump a scheduled place out to the backup list (instant, no rebuild).
  const removeItem = async (title: string) => {
    try {
      const res = await api.post<{ trip: Record<string, AgentPlanResult> }>(
        "/trip/itinerary/pick",
        { title, action: "remove" },
      );
      if (res.trip) {
        setTrip(res.trip);
        setItems(res.trip.itinerary?.items ?? []);
        toast.success(`Moved “${title}” to backup.`);
      }
    } catch {
      toast.error("Couldn't move that to backup.");
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
        Tick items off as you go — saved on your device, works offline. Reorder
        within a day with the arrows (or drag on desktop).
      </p>

      {/* Trip progress — the checklist you refer to on the ground. */}
      <div className="mb-4 flex items-center gap-3">
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--border)]">
          <div
            className="h-full rounded-full bg-[var(--success)] transition-[width] duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="shrink-0 text-xs font-medium text-[var(--muted)] tabular-nums">
          {doneCount}/{items.length} done
        </span>
      </div>

      <div className="space-y-4">
        {[...days.entries()]
          .sort(([a], [b]) => a - b)
          .map(([dayIndex, dayItems]) => (
            <DayItinerary
              key={dayIndex}
              dayIndex={dayIndex}
              dayItems={dayItems}
              onReorder={(from, to) => reorderDay(dayIndex, from, to)}
              onRemove={(title) => void removeItem(title)}
              itemKey={itemKey}
              isDone={isDone}
              onToggle={toggle}
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
  onRemove,
  itemKey,
  isDone,
  onToggle,
}: {
  dayIndex: number;
  dayItems: ItineraryItem[];
  onReorder: (from: number, to: number) => void;
  onRemove: (title: string) => void;
  itemKey: (item: ItineraryItem) => string;
  isDone: (key: string) => boolean;
  onToggle: (key: string) => void;
}) {
  const [drag, setDrag] = useState<number | null>(null);
  const dayDone = dayItems.filter((i) => isDone(itemKey(i))).length;
  return (
    <div>
      <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold text-[var(--brand-500)]">
        Day {dayIndex}
        <span className="text-[0.7rem] font-normal text-[var(--muted)] tabular-nums">
          {dayDone}/{dayItems.length}
        </span>
      </h4>
      <ol className="space-y-1.5">
        {dayItems.map((item, idx) => {
          const key = itemKey(item);
          const done = isDone(key);
          return (
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
              "surface-card flex items-start gap-2 p-3 transition-opacity",
              drag === idx && "opacity-50",
              done && "opacity-60",
            )}
          >
            {/* Tick it off — the offline checklist */}
            <button
              type="button"
              aria-label={done ? "Mark not done" : "Mark done"}
              onClick={() => onToggle(key)}
              className={cn(
                "mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-[var(--r-sm)] border transition-colors",
                done
                  ? "border-[var(--success)] bg-[var(--success)] text-white"
                  : "border-[var(--border)] text-transparent hover:border-[var(--success)]",
              )}
            >
              <Check className="h-3.5 w-3.5" />
            </button>
            <GripHorizontal className="mt-0.5 hidden h-4 w-4 shrink-0 cursor-grab text-[var(--muted)] active:cursor-grabbing sm:block" />
            <div className="min-w-0 flex-1">
              <p className={cn("text-sm font-medium", done && "line-through text-[var(--muted)]")}>{item.title}</p>
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
                    <Money amount={item.cost_amount} currency={item.cost_currency ?? "MYR"} />
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
              {/* Only real places can go to backup — not flights/hotels/transport. */}
              {(item.kind === "activity" || item.kind === "meal") && (
                <button
                  type="button"
                  aria-label="Move to backup"
                  title="Move to backup"
                  onClick={() => onRemove(item.title)}
                  className="grid h-7 w-7 place-items-center rounded-[var(--r-sm)] text-[var(--muted)] hover:bg-[color-mix(in_srgb,var(--accent)_14%,transparent)] hover:text-[var(--accent)]"
                >
                  <ArrowDown className="h-4 w-4 rotate-[135deg]" />
                </button>
              )}
            </div>
          </li>
          );
        })}
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
