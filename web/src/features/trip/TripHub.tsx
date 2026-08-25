import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Briefcase,
  History as HistoryIcon,
  ArrowLeft,
  Plane,
  Clock,
  CreditCard,
  ShoppingCart,
  Loader2,
  Trash2,
} from "@/components/ui/icons";
import {
  Badge,
  Button,
  EmptyState,
  Skeleton,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  confirm,
} from "@/components/ui";
import { Page, PageHeader } from "@/components/layout/Page";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { usePlanStore, type PlanResults } from "@/stores/planStore";
import { MyTrip } from "@/features/trip/MyTrip";
import { History } from "@/features/history/History";
import { BookingsHub } from "@/features/trip/BookingsHub";

/** Flat (no-gradient) banner colours, chosen by destination so cards vary. */
const BANDS = ["#0F766E", "#1D4ED8", "#B45309", "#15803D", "#7E22CE", "#0E7490"];
function bandFor(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return BANDS[h % BANDS.length];
}

/** Module cache so a destination's compressed thumbnail is fetched once. */
const thumbCache = new Map<string, string | null>();

function formatWhen(value: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/**
 * Trip destination — a gallery of the traveller's trips as cards (grouped, since
 * you may have several), opening one into its full detail. History (searches +
 * bookings) sits in a second tab.
 */
export function TripHub() {
  const [params, setParams] = useSearchParams();
  const [openResults, setOpenResults] = useState<PlanResults | null>(null);
  // `?open=active` deep-links straight into the active trip's detail (MyTrip
  // reads GET /trip). Home's "active trip" card and the "plan ready" banner use
  // it so a tap lands on the plan itself, not the gallery or History.
  const openActive = params.get("open") === "active";

  if (openActive || openResults) {
    const back = () => {
      setOpenResults(null);
      if (openActive) {
        const next = new URLSearchParams(params);
        next.delete("open");
        setParams(next, { replace: true });
      }
    };
    return (
      <Page width="xl">
        {/* A back affordance, not a breadcrumb: this is a push/pop navigation, so
            the control sits where a native back button would and nothing else
            competes with it at the top of the detail view. */}
        <Button variant="ghost" size="sm" className="mb-3 -ml-2" onClick={back}>
          <ArrowLeft className="h-4 w-4" /> All trips
        </Button>
        <MyTrip />
      </Page>
    );
  }

  return (
    <Page width="xl">
      <PageHeader
        eyebrow="Your travel"
        title="Trips"
        subtitle="Everything you've committed to — plus the orders, payments and searches behind them."
      />
      <TripTabs onOpen={setOpenResults} />
    </Page>
  );
}

const TRIP_TABS = [
  { value: "trips", label: "Trips", icon: Briefcase },
  { value: "orders", label: "Orders", icon: ShoppingCart },
  { value: "payments", label: "Payments", icon: CreditCard },
  { value: "history", label: "History", icon: HistoryIcon },
] as const;

function TripTabs({ onOpen }: { onOpen: (r: PlanResults) => void }) {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "trips";
  const setTab = (value: string) =>
    setParams(value === "trips" ? {} : { tab: value }, { replace: true });

  return (
    <Tabs value={tab} onValueChange={setTab}>
      {/* Sticky under the top bar so switching tab never means scrolling back up.
          `TabsList` already scrolls sideways and centres the active chip, so the
          hand-rolled overflow wrapper that used to be here is gone. */}
      <div
        className="sticky z-10 -mx-4 bg-[var(--bg)]/85 px-4 py-2 backdrop-blur-md md:-mx-6 md:px-6"
        style={{ top: "var(--top-bar)" }}
      >
        <TabsList>
          {TRIP_TABS.map(({ value, label, icon: Icon }) => (
            <TabsTrigger key={value} value={value}>
              <Icon className="h-4 w-4" weight={tab === value ? "fill" : "regular"} /> {label}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
      <TabsContent value="trips">
        <TripsGallery onOpen={onOpen} />
      </TabsContent>
      <TabsContent value="orders">
        <BookingsHub mode="pending" />
      </TabsContent>
      <TabsContent value="payments">
        <BookingsHub mode="payments" />
      </TabsContent>
      <TabsContent value="history">
        <History />
      </TabsContent>
    </Tabs>
  );
}

// --------------------------------------------------------------------------- //

type SavedTrip = {
  id: string; title: string; destination: string | null; scope: string; created_at: string | null;
  summary?: TripSummary | null;
};

function TripsGallery({ onOpen }: { onOpen: (r: PlanResults) => void }) {
  const setResults = usePlanStore((s) => s.setResults);
  const [opening, setOpening] = useState<string | null>(null);
  const qc = useQueryClient();

  // Only trips the traveller CONFIRMED ("Add to my trip") — not every search.
  // Raw searches stay in the History tab.
  const { data, isLoading } = useQuery({
    queryKey: ["confirmed-trips"],
    queryFn: () => api.get<{ saved: SavedTrip[] }>("/saved?kind=trip").then((d) => d.saved),
  });

  const deleteTrip = async (t: SavedTrip) => {
    const ok = await confirm({
      title: "Delete this trip?",
      body: "It's removed from your trips. Past searches stay in History.",
      confirmText: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del(`/saved/${t.id}`);
      await qc.invalidateQueries({ queryKey: ["confirmed-trips"] });
      toast.success("Trip deleted.");
    } catch {
      toast.error("Could not delete that trip.");
    }
  };

  const trips = data ?? [];

  const openTrip = async (t: SavedTrip) => {
    setOpening(t.id);
    try {
      const full = await api.get<{ scope: string; results: PlanResults }>(`/saved/${t.id}`);
      if (!full.results) {
        toast.error("That trip couldn't be opened.");
        return;
      }
      setResults(full.results, full.scope);
      // Opening a saved trip makes it the ACTIVE trip so the detail view (which
      // reads GET /trip) shows *this* trip — not the last one or an empty state.
      await api.post("/trip/save", { results: full.results }).catch(() => {});
      onOpen(full.results);
    } catch {
      toast.error("Could not open that trip.");
    } finally {
      setOpening(null);
    }
  };

  if (isLoading) {
    return (
      <div className="grid gap-4 py-2 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-56 w-full rounded-[var(--r-xl)]" />
        ))}
      </div>
    );
  }

  // Only trips the traveller confirmed with "Add to my trip" appear here — a
  // raw plan result the agents produced is NOT a trip until it's added. Those
  // live in the results view and in History.
  if (trips.length === 0) {
    return (
      <div className="py-10">
        <EmptyState
          icon={<Briefcase className="h-10 w-10" />}
          title="No trips yet"
          description="Plan from Home, then tap “Add to my trip” to keep it here. Every search stays in History."
        />
      </div>
    );
  }

  return (
    <div className="grid gap-4 py-2 sm:grid-cols-2 lg:grid-cols-3">
      {trips.map((t) => (
        <TripCard
          key={t.id}
          title={t.destination || t.title || "Trip"}
          subtitle={t.title}
          band={bandFor(t.destination || t.title || t.id)}
          when={formatWhen(t.created_at)}
          loading={opening === t.id}
          thumbKey={t.destination || undefined}
          summary={t.summary}
          savedId={t.id}
          onClick={() => void openTrip(t)}
          onDelete={() => void deleteTrip(t)}
        />
      ))}
    </div>
  );
}

type TripSummary = {
  flights: { count: number; atlas: number; research: number; bookable: number; picked: boolean };
  places: { suggested: number; scheduled: number };
  eats: { suggested: number };
};
type ReplanAlt = { id: string; title: string; price_amount: number | null; price_currency: string | null; bookable: boolean; within_budget: boolean | null };
type ReplanResult = {
  status: string; route: string;
  disrupted: { title: string | null; price_amount: number | null; price_currency: string | null };
  alternatives: ReplanAlt[];
  budget: { amount: number | null; currency: string; within_budget_count: number; total: number };
};

function TripCard({
  title,
  subtitle,
  band,
  when,
  optionCount,
  badge,
  loading,
  thumbKey,
  summary,
  savedId,
  onClick,
  onDelete,
}: {
  title: string;
  subtitle?: string;
  band: string;
  when?: string;
  optionCount?: number;
  badge?: string;
  loading?: boolean;
  thumbKey?: string;
  summary?: TripSummary | null;
  savedId?: string;
  onClick: () => void;
  onDelete?: () => void;
}) {
  const [thumb, setThumb] = useState<string | null>(thumbKey ? thumbCache.get(thumbKey) ?? null : null);
  useEffect(() => {
    if (!thumbKey || thumbCache.has(thumbKey)) return;
    let cancelled = false;
    api
      .get<{ thumbnail: string | null }>(`/trip/thumbnail?destination=${encodeURIComponent(thumbKey)}`)
      .then((d) => {
        thumbCache.set(thumbKey, d.thumbnail);
        if (!cancelled) setThumb(d.thumbnail);
      })
      .catch(() => thumbCache.set(thumbKey, null));
    return () => { cancelled = true; };
  }, [thumbKey]);

  const [replanning, setReplanning] = useState(false);
  const [replan, setReplan] = useState<ReplanResult | null>(null);
  const runReplan = async () => {
    if (!savedId) return;
    setReplanning(true);
    try {
      setReplan(await api.post<ReplanResult>("/trip/replan-flights", { saved_id: savedId, simulate: "delayed" }));
    } catch {
      toast.error("Couldn't re-plan flights.");
    } finally {
      setReplanning(false);
    }
  };

  const f = summary?.flights;
  return (
    <div className="surface-card group pressable relative overflow-hidden p-0 hover:border-[var(--brand-400)] hover:shadow-[var(--shadow-2)]">
      {/* Banner is the open target */}
      <button onClick={onClick} disabled={loading} className="block w-full text-left disabled:opacity-70">
        <div className="relative flex h-36 items-end overflow-hidden p-4" style={{ background: band }}>
          {thumb && <img src={thumb} alt="" className="absolute inset-0 h-full w-full object-cover" />}
          {/* A scrim, not decoration — the title has to stay legible over an
              arbitrary photo, and the flat palette rule is about brand fills. */}
          <span className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/20 to-black/5" />
          <Plane className="absolute right-3.5 top-3.5 h-6 w-6 text-white/85 drop-shadow" weight="fill" />
          <div className="relative min-w-0">
            <span className="block truncate font-[family-name:var(--font-display)] text-[1.4rem] font-bold leading-tight tracking-[-0.02em] text-white drop-shadow">
              {title}
            </span>
            {when && (
              <span className="mt-1 flex items-center gap-1 text-[0.7rem] font-medium text-white/75">
                <Clock className="h-3 w-3" /> {when}
              </span>
            )}
          </div>
          {badge && (
            <span className="absolute left-4 top-3.5 rounded-[var(--r-pill)] bg-white/25 px-2 py-0.5 text-[0.6rem] font-semibold uppercase tracking-[0.08em] text-white backdrop-blur-sm">
              {badge}
            </span>
          )}
        </div>
        {subtitle && (
          <p className="line-clamp-2 px-4 pt-3.5 text-[0.9375rem] font-medium leading-snug">{subtitle}</p>
        )}
      </button>

      {/* Details + interactive re-plan (outside the open-button) */}
      <div className="space-y-2 px-4 pb-4 pt-2.5">
        {/* Stats as pills rather than a run of glyph-prefixed sentences — they're
            scannable at a glance, which is the whole job of a gallery card. */}
        <div className="flex flex-wrap items-center gap-1.5">
          {f && f.count > 0 && (
            <Stat
              icon={<Plane className="h-3 w-3" weight="fill" />}
              label={`${f.count} flight${f.count === 1 ? "" : "s"}`}
              tone={f.picked ? "good" : "warn"}
            />
          )}
          {summary && summary.places.suggested > 0 && (
            <Stat label={`${summary.places.scheduled}/${summary.places.suggested} places set`} />
          )}
          {summary && summary.eats.suggested > 0 && (
            <Stat label={`${summary.eats.suggested} to eat`} />
          )}
          {typeof optionCount === "number" && optionCount > 0 && <Badge>{optionCount} options</Badge>}
        </div>
        {f && f.count > 0 && (
          <p className="text-[0.7rem] text-[var(--muted)]">
            {f.atlas} Atlas · {f.research} research · {f.picked ? "one picked" : "none picked yet"}
          </p>
        )}

        {savedId && f && f.count > 0 && (
          <div className="pt-1">
            {!replan ? (
              <button
                onClick={runReplan}
                disabled={replanning}
                className="pressable flex w-full items-center justify-center gap-1.5 rounded-[var(--r-md)] border border-[var(--border)] px-3 py-2 text-xs font-semibold text-[var(--brand-600)] hover:border-[var(--brand-400)] hover:bg-[var(--bg)] disabled:opacity-60"
              >
                {replanning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plane className="h-3.5 w-3.5" />}
                {replanning ? "Re-planning…" : "Flight delayed? Re-plan"}
              </button>
            ) : (
              <div className="rounded-[var(--r-md)] border-l-2 border-[var(--warning)] bg-[color-mix(in_srgb,var(--warning)_8%,transparent)] p-2.5">
                <p className="text-xs font-semibold text-[var(--warning)]">
                  ⚠ {replan.disrupted.title || "Flight"} {replan.status} on {replan.route}
                </p>
                <p className="mt-0.5 text-[0.65rem] text-[var(--muted)]">
                  {replan.budget.amount != null
                    ? `${replan.budget.within_budget_count}/${replan.budget.total} alternatives within your ${replan.budget.currency} ${replan.budget.amount.toLocaleString()} budget`
                    : `${replan.alternatives.length} alternatives found`}
                </p>
                <div className="mt-1.5 space-y-1">
                  {replan.alternatives.slice(0, 3).map((a) => (
                    <div key={a.id} className="flex items-center gap-1.5 text-[0.7rem]">
                      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", a.within_budget === false ? "bg-[var(--warning)]" : "bg-[var(--success)]")} />
                      <span className="min-w-0 flex-1 truncate">{a.title}</span>
                      {a.price_amount != null && (
                        <span className="shrink-0 font-medium">{a.price_currency} {Number(a.price_amount).toLocaleString()}</span>
                      )}
                    </div>
                  ))}
                </div>
                <button onClick={() => setReplan(null)} className="mt-1 text-[0.65rem] text-[var(--muted)] hover:underline">
                  Dismiss
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {onDelete && (
        <button
          aria-label="Remove trip"
          data-fixed-size
          onClick={(event) => {
            event.stopPropagation();
            onDelete();
          }}
          className={cn(
            "tap-target absolute right-3 top-3 grid h-8 w-8 place-items-center rounded-full",
            "bg-black/40 text-white shadow backdrop-blur-sm",
            "transition-[background-color,opacity] duration-[var(--dur)] hover:bg-[var(--danger)]",
            // Visible by default: hover-to-reveal made this unreachable on touch,
            // where there is no hover. It only hides on hover-capable pointers.
            "[@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100",
            "focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
          )}
        >
          <Trash2 className="h-4 w-4" />
        </button>
      )}
      {loading && (
        <span className="absolute inset-0 grid place-items-center bg-[var(--surface)]/70 backdrop-blur-[1px]">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--brand-500)]" />
        </span>
      )}
    </div>
  );
}

/** One scannable fact on a trip card. `tone` flags whether it still needs you. */
function Stat({
  icon,
  label,
  tone = "neutral",
}: {
  icon?: ReactNode;
  label: string;
  tone?: "neutral" | "good" | "warn";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-[var(--r-pill)] px-2 py-[0.1875rem] text-[0.6875rem] font-semibold",
        tone === "good" &&
          "bg-[color-mix(in_srgb,var(--success)_12%,transparent)] text-[var(--success)]",
        tone === "warn" &&
          "bg-[color-mix(in_srgb,var(--warning)_14%,transparent)] text-[var(--warning)]",
        tone === "neutral" &&
          "bg-[color-mix(in_srgb,var(--text)_6%,transparent)] text-[var(--muted)]",
      )}
    >
      {icon}
      {label}
    </span>
  );
}
