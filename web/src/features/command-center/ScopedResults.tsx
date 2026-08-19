import { ArrowLeft, Briefcase, Cloud, RotateCcw, ShieldAlert, TrendingUp } from "@/components/ui/icons";
import { Badge, Button, OptionCard } from "@/components/ui";
import { SourceTrustRow } from "@/components/ui/SourceBadge";
import { FlightResults } from "@/features/flights/FlightResults";
import type { AgentPlanResult, PlanOption, PlanResults, Scope } from "@/lib/types";

/**
 * Renders only the panels the chosen scope produced.
 *
 * This is the other half of scoping: running fewer agents is pointless if the
 * page still renders 12 empty sections. `scope.panels` decides what appears, in
 * the order that scope considers most useful.
 */

export function ScopedResults({
  scope,
  results,
  onAskAgain,
  onBack,
  onOpenTrip,
}: {
  scope: Scope;
  results: PlanResults;
  onAskAgain: () => void;
  onBack: () => void;
  onOpenTrip: () => void;
}) {
  const panels = (results._scope?.panels?.length ? results._scope.panels : scope.panels) ?? [];
  const agents = results._scope?.agents ?? scope.agents;

  return (
    <div className="mx-auto w-full max-w-5xl">
      <div className="flex flex-wrap items-center gap-2 pt-2 pb-4">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          All modes
        </Button>
        <Button variant="ghost" size="sm" onClick={onAskAgain}>
          <RotateCcw className="h-4 w-4" />
          Ask again
        </Button>
        <div className="min-w-0 flex-1" />
        <Badge variant="brand">{scope.label}</Badge>
        <Badge>{agents.length} agents ran</Badge>
      </div>

      <div className="space-y-8">
        {panels.map((panel) => (
          <Panel key={panel} name={panel} results={results} onOpenTrip={onOpenTrip} />
        ))}
      </div>
    </div>
  );
}

function Panel({
  name,
  results,
  onOpenTrip,
}: {
  name: string;
  results: PlanResults;
  onOpenTrip: () => void;
}) {
  switch (name) {
    case "summary":
      return <SummaryPanel results={results} onOpenTrip={onOpenTrip} />;
    case "flights":
      return results.flight ? <FlightResults result={results.flight} /> : null;
    case "hotels":
      return <OptionsPanel result={results.hotel} title="Stays" icon={Briefcase} />;
    case "dining":
      return (
        <OptionsPanel
          result={results.research}
          title="Food"
          icon={Briefcase}
          filter={(option) => option.kind === "restaurant"}
        />
      );
    case "activities":
      return (
        <OptionsPanel
          result={results.research}
          title="Things to do"
          icon={Briefcase}
          filter={(option) => option.kind === "activity"}
          extra={results.recommendation}
        />
      );
    case "itinerary":
      return <ItineraryPanel result={results.itinerary} />;
    case "budget":
      return <BudgetPanel result={results.budget} />;
    case "weather":
      return <WeatherPanel result={results.weather_risk} />;
    case "risk":
      return <RiskPanel result={results.risk_advisory} />;
    case "transport":
      return <DataPanel result={results.transport} title="Getting around" />;
    case "visa":
      return <DataPanel result={results.visa} title="Visa & entry" />;
    case "crowd":
      return <DataPanel result={results.crowd} title="Crowds" />;
    case "social":
      return <SocialPanel result={results.research} />;
    case "practical":
      return (
        <>
          <DataPanel result={results.emergency} title="Emergency contacts" />
          <DataPanel result={results.language} title="Language & etiquette" />
        </>
      );
    default:
      return null;
  }
}

function SummaryPanel({
  results,
  onOpenTrip,
}: {
  results: PlanResults;
  onOpenTrip: () => void;
}) {
  const chief = results.chief;
  if (!chief) return null;
  const data = chief.data as { destination?: string };
  const critic = results.critic?.data as { score?: number; retried?: boolean } | undefined;

  return (
    <section className="surface-card border-l-4 border-[var(--brand-500)] p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-[family-name:var(--font-display)] text-lg font-semibold tracking-tight">
            {data.destination ?? "Your request"}
          </h3>
          <p className="mt-0.5 text-sm text-[var(--muted)]">{chief.summary}</p>
        </div>
        {results.itinerary && (
          <Button variant="secondary" size="sm" onClick={onOpenTrip}>
            Open My Trip
          </Button>
        )}
      </div>

      {critic?.score != null && (
        <p className="mt-3 text-xs text-[var(--muted)]">
          Critic scored this {critic.score.toFixed(2)}
          {critic.retried ? " and re-ran the weakest agent." : "."}
        </p>
      )}
    </section>
  );
}

function OptionsPanel({
  result,
  title,
  icon: Icon,
  filter,
  extra,
}: {
  result?: AgentPlanResult;
  title: string;
  icon: typeof Briefcase;
  filter?: (option: PlanOption) => boolean;
  extra?: AgentPlanResult;
}) {
  const own = result?.options ?? [];
  const extras = extra?.options ?? [];
  const options = [...own, ...extras].filter((option) => !filter || filter(option));
  if (options.length === 0) return null;

  return (
    <section>
      <h3 className="mb-3 flex items-center gap-2 text-lg font-semibold">
        <Icon className="h-5 w-5 text-[var(--brand-500)]" />
        {title}
        <Badge variant="brand">{options.length}</Badge>
      </h3>
      {result?.summary && (
        <p className="mb-3 text-sm text-[var(--muted)]">{result.summary}</p>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {options.map((option) => (
          <div key={option.id} className="surface-card flex flex-col p-4">
            <div className="flex items-start justify-between gap-2">
              <p className="min-w-0 text-sm font-semibold">{option.title}</p>
              {option.price_amount != null && (
                <span className="shrink-0 text-sm font-semibold text-[var(--brand-500)]">
                  {option.price_currency} {Number(option.price_amount).toLocaleString()}
                </span>
              )}
            </div>
            {option.reasoning && (
              <p className="mt-1.5 flex-1 text-xs italic text-[var(--muted)]">
                {option.reasoning}
              </p>
            )}
            <div className="mt-2.5 border-t border-[var(--border)] pt-2">
              <SourceTrustRow option={option} />
            </div>
          </div>
        ))}
      </div>
      {(result?.warnings ?? []).length > 0 && (
        <ul className="mt-3 space-y-1">
          {result!.warnings.map((warning, index) => (
            <li key={index} className="text-[0.7rem] text-[var(--warning)]">
              {warning}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ItineraryPanel({ result }: { result?: AgentPlanResult }) {
  const items = result?.items ?? [];
  if (items.length === 0) return null;

  const days = new Map<number, typeof items>();
  for (const item of items) {
    days.set(item.day_index, [...(days.get(item.day_index) ?? []), item]);
  }

  return (
    <section>
      <h3 className="mb-3 flex items-center gap-2 text-lg font-semibold">
        Itinerary <Badge variant="brand">{items.length} items</Badge>
      </h3>
      <div className="space-y-4">
        {[...days.entries()]
          .sort(([a], [b]) => a - b)
          .map(([day, dayItems]) => (
            <div key={day}>
              <h4 className="mb-2 text-sm font-semibold text-[var(--brand-500)]">
                Day {day}
              </h4>
              <ol className="ml-2 space-y-1.5 border-l-2 border-[var(--border)] pl-4">
                {dayItems.map((item, index) => (
                  <li key={index} className="relative">
                    <span className="absolute -left-[1.25rem] top-1.5 h-2 w-2 rounded-full bg-[var(--brand-400)]" />
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
                          {item.cost_currency ?? "MYR"}{" "}
                          {Number(item.cost_amount).toLocaleString()}
                        </span>
                      )}
                    </div>
                    {item.reasoning && (
                      <p className="mt-0.5 text-xs italic text-[var(--muted)]">
                        {item.reasoning}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          ))}
      </div>
    </section>
  );
}

function BudgetPanel({ result }: { result?: AgentPlanResult }) {
  if (!result) return null;
  const data = result.data as {
    spent_estimate?: number;
    budget_amount?: number | null;
    remaining?: number | null;
    over_budget?: boolean;
    currency?: string;
    breakdown?: Record<string, number>;
  };
  const currency = data.currency ?? "MYR";
  const total = data.budget_amount ?? 0;
  const spent = data.spent_estimate ?? 0;
  const pct = total > 0 ? Math.min(100, Math.round((spent / total) * 100)) : 0;

  return (
    <section>
      <h3 className="mb-3 flex items-center gap-2 text-lg font-semibold">
        <TrendingUp className="h-5 w-5 text-[var(--brand-500)]" />
        Budget
        <Badge variant={data.over_budget ? "danger" : "success"}>
          {data.over_budget ? "Over budget" : "On track"}
        </Badge>
      </h3>
      <div className="surface-card space-y-3 p-4">
        <p className="text-sm text-[var(--muted)]">{result.summary}</p>
        {total > 0 && (
          <div className="h-2 overflow-hidden rounded-full bg-[var(--border)]">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${pct}%`,
                backgroundColor: data.over_budget ? "var(--danger)" : "var(--brand-500)",
              }}
            />
          </div>
        )}
        {data.breakdown && (
          <div className="grid grid-cols-2 gap-2 border-t border-[var(--border)] pt-2 sm:grid-cols-4">
            {(["flights", "hotels_total", "activities", "nights"] as const).map((key) => (
              <div key={key} className="text-center">
                <p className="text-xs text-[var(--muted)]">{key.replace(/_/g, " ")}</p>
                <p className="text-sm font-semibold">
                  {key === "nights"
                    ? (data.breakdown?.[key] ?? "—")
                    : `${currency} ${Number(data.breakdown?.[key] ?? 0).toLocaleString()}`}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function WeatherPanel({ result }: { result?: AgentPlanResult }) {
  if (!result) return null;
  const data = result.data as {
    risk_level?: string;
    forecast?: Array<{
      date: string;
      high_c: number;
      low_c: number;
      precipitation_pct: number;
      description: string;
    }>;
  };
  const level = data.risk_level ?? "unknown";
  const variant = level === "high" ? "danger" : level === "medium" ? "warning" : "success";

  return (
    <section>
      <h3 className="mb-3 flex items-center gap-2 text-lg font-semibold">
        <Cloud className="h-5 w-5 text-[var(--brand-500)]" />
        Weather
        <Badge variant={variant}>{level} risk</Badge>
      </h3>
      <div className="surface-card p-4">
        <p className="mb-3 text-sm text-[var(--muted)]">{result.summary}</p>
        {data.forecast && data.forecast.length > 0 && (
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-7">
            {data.forecast.slice(0, 7).map((day) => (
              <div
                key={day.date}
                className="rounded-[var(--r-sm)] bg-[color-mix(in_srgb,var(--brand-400)_6%,transparent)] p-2 text-center"
                title={day.description}
              >
                <p className="text-[0.6rem] text-[var(--muted)]">{day.date.slice(5)}</p>
                <p className="text-xs font-semibold">{day.high_c}°</p>
                <p className="text-[0.6rem] text-[var(--muted)]">{day.low_c}°</p>
                {day.precipitation_pct >= 60 && (
                  <p className="text-[0.55rem] text-[var(--warning)]">
                    {day.precipitation_pct}%
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function RiskPanel({ result }: { result?: AgentPlanResult }) {
  if (!result) return null;
  const data = result.data as {
    safety_level?: string;
    active_threats?: string[];
    safe_months?: string[];
    recommended_action?: string;
  };
  const level = data.safety_level ?? "unknown";
  const dangerous = level === "dangerous";

  return (
    <section>
      <h3 className="mb-3 flex items-center gap-2 text-lg font-semibold">
        <ShieldAlert
          className={`h-5 w-5 ${dangerous ? "text-[var(--danger)]" : "text-[var(--warning)]"}`}
        />
        Safety
        <Badge variant={dangerous ? "danger" : level === "safe" ? "success" : "warning"}>
          {level}
        </Badge>
        {data.recommended_action && <Badge>{data.recommended_action}</Badge>}
      </h3>
      <div className="surface-card space-y-2 p-4">
        <p className="text-sm">{result.summary}</p>
        {(data.active_threats ?? []).length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {data.active_threats!.map((threat) => (
              <Badge key={threat} variant="danger">
                {threat}
              </Badge>
            ))}
          </div>
        )}
        {(data.safe_months ?? []).length > 0 && (
          <p className="text-xs text-[var(--muted)]">
            Safer months: {data.safe_months!.join(", ")}
          </p>
        )}
        {result.warnings.map((warning, index) => (
          <p key={index} className="text-xs text-[var(--warning)]">
            {warning}
          </p>
        ))}
      </div>
    </section>
  );
}

function SocialPanel({ result }: { result?: AgentPlanResult }) {
  if (!result) return null;
  const data = result.data as {
    social_signal?: { score: number | null; label: string; confidence: string };
    contradictions?: Array<{ topic: string; claim: string; counter_claim: string }>;
    sources_crawled?: string[];
  };
  const signal = data.social_signal;
  const contradictions = data.contradictions ?? [];
  if (!signal && contradictions.length === 0) return null;

  return (
    <section className="surface-card p-4">
      <h3 className="mb-2 text-sm font-semibold">Social Signal</h3>
      {signal?.score != null ? (
        <>
          <div className="flex items-center gap-3">
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--border)]">
              <div
                className="h-full rounded-full bg-gradient-to-r from-[var(--brand-500)] to-[var(--accent)]"
                style={{ width: `${Math.round(signal.score * 100)}%` }}
              />
            </div>
            <span className="text-sm font-semibold tabular-nums">
              {Math.round(signal.score * 100)}
            </span>
          </div>
          <p className="mt-1.5 text-[0.65rem] italic text-[var(--muted)]">{signal.label}</p>
        </>
      ) : (
        <p className="text-xs text-[var(--muted)]">
          Not enough public signal to score this yet.
        </p>
      )}

      {contradictions.length > 0 && (
        <div className="mt-3 border-t border-[var(--border)] pt-3">
          <p className="mb-1.5 text-xs font-medium">Sources disagree</p>
          <ul className="space-y-1.5">
            {contradictions.map((entry, index) => (
              <li key={index} className="text-[0.65rem] leading-relaxed">
                <span className="font-medium">{entry.topic}: </span>
                <span className="text-[var(--muted)]">{entry.claim}</span>
                {entry.counter_claim && (
                  <>
                    <span className="font-medium text-[var(--warning)]"> — but </span>
                    <span className="text-[var(--muted)]">{entry.counter_claim}</span>
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/** Generic renderer for the advisory agents, whose payloads are free-form. */
function DataPanel({ result, title }: { result?: AgentPlanResult; title: string }) {
  if (!result) return null;
  const entries = Object.entries(result.data ?? {}).filter(
    ([key, value]) =>
      key !== "destination" &&
      value !== null &&
      value !== "" &&
      !(Array.isArray(value) && value.length === 0),
  );

  return (
    <section>
      <h3 className="mb-2 text-lg font-semibold">{title}</h3>
      <div className="surface-card space-y-2 p-4">
        <p className="text-sm text-[var(--muted)]">{result.summary}</p>
        <dl className="grid gap-2 sm:grid-cols-2">
          {entries.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="text-[0.65rem] uppercase tracking-wide text-[var(--muted)]">
                {key.replace(/_/g, " ")}
              </dt>
              <dd className="break-words text-xs">{renderValue(value)}</dd>
            </div>
          ))}
        </dl>
        {result.warnings.map((warning, index) => (
          <p key={index} className="text-xs text-[var(--warning)]">
            {warning}
          </p>
        ))}
      </div>
    </section>
  );
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) {
    return value
      .map((item) => (typeof item === "object" ? JSON.stringify(item) : String(item)))
      .join(", ");
  }
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .filter(([, entry]) => entry !== null && entry !== "")
      .map(([key, entry]) => `${key}: ${entry}`)
      .join(" · ");
  }
  return String(value);
}

export { OptionCard };
