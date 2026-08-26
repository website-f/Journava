import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Scales, Sparkles, X, Plane, Building2, ShieldAlert, Wallet, Compass } from "@/components/ui/icons";
import { Button, EmptyState, Skeleton } from "@/components/ui";
import { Page, PageHeader } from "@/components/layout/Page";
import { api } from "@/lib/api";
import { useCompareStore } from "@/stores/compareStore";

type Priced = { title?: string; price_amount?: number; price_currency?: string; bookable?: boolean } | null;
type TripSummary = {
  saved_id: string;
  destination: string;
  dates: { start?: string | null; end?: string | null; days?: number | null };
  travellers?: number | null;
  budget: { planned?: number | null; estimated_spend?: number | null; currency?: string; over_budget?: boolean | null };
  cheapest_flight: Priced;
  cheapest_hotel: Priced;
  risk_level?: string | null;
  weather?: string | null;
  social_score?: number | null;
  top_attractions?: string[];
};

const PRESETS = [
  { label: "Cheapest overall", q: "Which trip is the cheapest overall once flights and hotels are counted?" },
  { label: "Safest", q: "Which trip is the safest right now, and why?" },
  { label: "Best for next January", q: "Which of these is the best to go to next January, considering weather, price and safety?" },
  { label: "Best value", q: "Which trip is the best value for money overall?" },
];

function money(amount?: number | null, currency?: string): string {
  if (amount == null) return "—";
  return `${currency ?? "MYR"} ${Number(amount).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export function ComparePage() {
  const ids = useCompareStore((s) => s.ids);
  const remove = useCompareStore((s) => s.remove);
  const clear = useCompareStore((s) => s.clear);

  const [trips, setTrips] = useState<TripSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [answer, setAnswer] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [q, setQ] = useState("");

  const idsKey = useMemo(() => ids.join(","), [ids]);

  useEffect(() => {
    let cancelled = false;
    if (ids.length === 0) {
      setTrips([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    api
      .post<{ trips: TripSummary[] }>("/compare/summaries", { saved_ids: ids })
      .then((res) => {
        if (!cancelled) setTrips(res.trips ?? []);
      })
      .catch(() => !cancelled && setTrips([]))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);

  const ask = async (question: string) => {
    if (!question.trim() || ids.length < 2) return;
    setAsking(true);
    setAnswer(null);
    try {
      const res = await api.post<{ answer: string }>("/compare/analyze", { saved_ids: ids, question });
      setAnswer(res.answer);
    } catch {
      setAnswer("Couldn't reach the comparison model — try again.");
    } finally {
      setAsking(false);
    }
  };

  if (ids.length === 0) {
    return (
      <Page width="xl">
        <PageHeader eyebrow="Decide" title="Compare trips" subtitle="Put your planned trips side by side." />
        <div className="py-10">
          <EmptyState
            icon={<Scales className="h-10 w-10" />}
            title="Your comparison is empty"
            description="Plan a few trips and tap “Add to compare” on each — then weigh them here, or ask the assistant which is best."
            action={
              <Button asChild variant="secondary">
                <Link to="/">Plan a trip</Link>
              </Button>
            }
          />
        </div>
      </Page>
    );
  }

  const ROWS: Array<{ label: string; icon: ReactNode; get: (t: TripSummary) => ReactNode }> = [
    { label: "Dates", icon: <Compass className="h-4 w-4" />, get: (t) => (t.dates.start ? `${t.dates.start} → ${t.dates.end ?? ""}` : t.dates.days ? `${t.dates.days} days` : "flexible") },
    { label: "Est. spend", icon: <Wallet className="h-4 w-4" />, get: (t) => (
      <span className={t.budget.over_budget ? "text-[var(--danger)]" : undefined}>
        {money(t.budget.estimated_spend ?? t.budget.planned, t.budget.currency)}
      </span>
    ) },
    { label: "Cheapest flight", icon: <Plane className="h-4 w-4" />, get: (t) => (t.cheapest_flight ? money(t.cheapest_flight.price_amount, t.cheapest_flight.price_currency) : "—") },
    { label: "Cheapest stay", icon: <Building2 className="h-4 w-4" />, get: (t) => (t.cheapest_hotel ? money(t.cheapest_hotel.price_amount, t.cheapest_hotel.price_currency) : "—") },
    { label: "Safety", icon: <ShieldAlert className="h-4 w-4" />, get: (t) => (
      t.risk_level ? (
        <span className={
          t.risk_level === "high" ? "text-[var(--danger)]" : t.risk_level === "medium" ? "text-[var(--warning)]" : "text-[var(--success)]"
        }>{t.risk_level} risk</span>
      ) : "—"
    ) },
  ];

  return (
    <Page width="xl">
      <PageHeader
        eyebrow="Decide"
        title="Compare trips"
        subtitle="The numbers side by side — then ask the assistant which one wins for you."
      />

      {/* Ask the assistant */}
      <div className="surface-card mb-6 p-4">
        <div className="mb-2 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-[var(--accent)]" weight="fill" />
          <h3 className="text-sm font-semibold">Ask your agent to compare</h3>
        </div>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button
              key={p.label}
              onClick={() => void ask(p.q)}
              disabled={asking || ids.length < 2}
              className="rounded-[var(--r-pill)] border border-[var(--border)] px-3 py-1.5 text-xs font-medium transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:opacity-50"
            >
              {p.label}
            </button>
          ))}
        </div>
        <form
          className="mt-2 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(q);
          }}
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. which is best for a family with kids in December?"
            className="min-w-0 flex-1 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm"
          />
          <Button type="submit" size="sm" loading={asking} disabled={ids.length < 2}>
            Ask
          </Button>
        </form>
        {ids.length < 2 && (
          <p className="mt-2 text-xs text-[var(--muted)]">Add at least two trips to compare.</p>
        )}
        {(asking || answer) && (
          <div className="mt-3 rounded-[var(--r-md)] border-l-2 border-[var(--brand-500)] bg-[color-mix(in_srgb,var(--brand-400)_8%,transparent)] p-3 text-sm leading-relaxed">
            {asking ? "Weighing the options…" : answer}
          </div>
        )}
      </div>

      {/* One card per trip — stacked on phones, side-by-side from sm up. Each
          card lists the same facts as label/value rows, so it reads cleanly at
          any width instead of forcing a horizontal-scrolling wide table. */}
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {ids.map((id) => (
            <Skeleton key={id} className="h-64 w-full rounded-[var(--r-lg)]" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {trips.map((t) => (
            <div key={t.saved_id} className="surface-card relative p-4">
              <button
                onClick={() => remove(t.saved_id)}
                aria-label={`Remove ${t.destination}`}
                className="absolute right-2 top-2 rounded-full p-1 text-[var(--muted)] hover:text-[var(--danger)]"
              >
                <X className="h-4 w-4" />
              </button>
              <p className="truncate pr-6 font-[family-name:var(--font-display)] text-lg font-bold">
                {t.destination}
              </p>
              {t.social_score != null && (
                <p className="mt-0.5 text-[0.65rem] text-[var(--muted)]">buzz {Math.round(t.social_score * 100)}</p>
              )}
              <dl className="mt-3 space-y-2">
                {ROWS.map((row) => (
                  <div
                    key={row.label}
                    className="flex items-center justify-between gap-3 border-b border-dashed border-[var(--border)] pb-2 last:border-0 last:pb-0"
                  >
                    <dt className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-[var(--muted)]">
                      {row.icon}
                      {row.label}
                    </dt>
                    <dd className="min-w-0 break-words text-right text-sm font-medium tabular-nums">
                      {row.get(t)}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
      )}

      <div className="mt-6">
        <Button variant="ghost" size="sm" onClick={clear}>
          Clear comparison
        </Button>
      </div>
    </Page>
  );
}
