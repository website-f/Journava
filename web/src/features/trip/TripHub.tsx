import { useEffect, useState } from "react";
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
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { usePlanStore, type PlanResults } from "@/stores/planStore";
import { MyTrip } from "@/features/trip/MyTrip";
import { History } from "@/features/history/History";
import { BookingsHub } from "@/features/trip/BookingsHub";

const TRIP_SCOPES = new Set(["full_trip", "itinerary_only"]);

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
  const [openResults, setOpenResults] = useState<PlanResults | null>(null);

  if (openResults) {
    return (
      <div className="mx-auto w-full max-w-6xl">
        <Button variant="ghost" size="sm" className="mb-2" onClick={() => setOpenResults(null)}>
          <ArrowLeft className="h-4 w-4" /> All trips
        </Button>
        <MyTrip />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl">
      <TripTabs onOpen={setOpenResults} />
    </div>
  );
}

function TripTabs({ onOpen }: { onOpen: (r: PlanResults) => void }) {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "trips";
  const setTab = (value: string) =>
    setParams(value === "trips" ? {} : { tab: value }, { replace: true });

  return (
    <Tabs value={tab} onValueChange={setTab}>
      {/* Scroll the tab row on narrow screens rather than wrapping. */}
      <div className="no-scrollbar -mx-1 overflow-x-auto px-1 pb-1">
        <TabsList className="w-max flex-nowrap">
          <TabsTrigger value="trips" className="shrink-0">
            <Briefcase className="h-4 w-4" /> Trips
          </TabsTrigger>
          <TabsTrigger value="orders" className="shrink-0">
            <ShoppingCart className="h-4 w-4" /> Orders
          </TabsTrigger>
          <TabsTrigger value="payments" className="shrink-0">
            <CreditCard className="h-4 w-4" /> Payments
          </TabsTrigger>
          <TabsTrigger value="history" className="shrink-0">
            <HistoryIcon className="h-4 w-4" /> History
          </TabsTrigger>
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
  const current = usePlanStore((s) => s.results);
  const currentScope = usePlanStore((s) => s.activeScope);
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

  const removeCurrent = async () => {
    const ok = await confirm({
      title: "Remove the active trip?",
      body: "Your active trip is cleared. Confirmed trips + searches stay saved.",
      confirmText: "Remove",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.del("/trip");
      usePlanStore.getState().clear();
      toast.success("Active trip removed.");
    } catch {
      toast.error("Could not remove the trip.");
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
      onOpen(full.results);
    } catch {
      toast.error("Could not open that trip.");
    } finally {
      setOpening(null);
    }
  };

  const showCurrent = current && currentScope && TRIP_SCOPES.has(currentScope);
  const currentDestination =
    (current?.chief?.data as { destination?: string } | undefined)?.destination ?? "";

  if (isLoading && !showCurrent) {
    return (
      <div className="grid gap-3 py-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-48 w-full" />
        ))}
      </div>
    );
  }

  if (!showCurrent && trips.length === 0) {
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
    <div className="grid gap-3 py-3 sm:grid-cols-2 lg:grid-cols-3">
      {showCurrent && (
        <TripCard
          title={currentDestination || "Current trip"}
          subtitle={(current?._scope as { label?: string } | undefined)?.label ?? "Active plan"}
          band={bandFor("current")}
          badge="Active"
          thumbKey={currentDestination || undefined}
          onClick={() => onOpen(current!)}
          onDelete={() => void removeCurrent()}
        />
      )}
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
    <div className="surface-card group relative overflow-hidden p-0 transition-colors hover:border-[var(--brand-400)]">
      {/* Banner is the open target */}
      <button onClick={onClick} disabled={loading} className="block w-full text-left disabled:opacity-70">
        <div className="relative flex h-28 items-end overflow-hidden p-3" style={{ background: band }}>
          {thumb && <img src={thumb} alt="" className="absolute inset-0 h-full w-full object-cover" />}
          <span className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/10 to-transparent" />
          <Plane className="absolute right-3 top-3 h-6 w-6 text-white/80 drop-shadow" />
          <span className="relative font-[family-name:var(--font-display)] text-lg leading-tight text-white drop-shadow">
            {title}
          </span>
          {badge && (
            <span className="absolute left-3 top-3 rounded-[var(--r-pill)] bg-white/25 px-2 py-0.5 text-[0.6rem] font-semibold uppercase text-white backdrop-blur-sm">
              {badge}
            </span>
          )}
        </div>
        {subtitle && <p className="line-clamp-2 px-3 pt-3 text-sm font-medium">{subtitle}</p>}
      </button>

      {/* Details + interactive re-plan (outside the open-button) */}
      <div className="space-y-1.5 px-3 pb-3 pt-2">
        {f && f.count > 0 && (
          <p className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
            <Plane className="h-3 w-3 text-[var(--brand-500)]" />
            {f.count} flights ({f.atlas} Atlas · {f.research} research) —{" "}
            <span className="font-medium text-[var(--warning)]">{f.picked ? "picked" : "none picked yet"}</span>
          </p>
        )}
        {summary && (summary.places.suggested > 0 || summary.eats.suggested > 0) && (
          <p className="text-xs text-[var(--muted)]">
            ◆ {summary.places.suggested} places · {summary.places.scheduled} scheduled · 🍽 {summary.eats.suggested} to eat
            {summary.places.suggested > summary.places.scheduled && (
              <span className="text-[var(--warning)]"> · {summary.places.suggested - summary.places.scheduled} to pick</span>
            )}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-1.5">
          {typeof optionCount === "number" && optionCount > 0 && <Badge>{optionCount} options</Badge>}
          {when && (
            <span className="flex items-center gap-1 text-[0.65rem] text-[var(--muted)]">
              <Clock className="h-3 w-3" /> {when}
            </span>
          )}
        </div>

        {savedId && f && f.count > 0 && (
          <div className="pt-1">
            {!replan ? (
              <button
                onClick={runReplan}
                disabled={replanning}
                className="flex items-center gap-1.5 rounded-[var(--r-md)] border border-[var(--border)] px-2.5 py-1.5 text-xs font-medium text-[var(--brand-600)] hover:bg-[var(--bg)] disabled:opacity-60"
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
          onClick={(event) => {
            event.stopPropagation();
            onDelete();
          }}
          className="absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-full bg-black/30 text-white/90 opacity-0 shadow backdrop-blur-sm transition-opacity hover:bg-[var(--danger)] group-hover:opacity-100"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
      {loading && (
        <span className="absolute inset-0 grid place-items-center bg-[var(--surface)]/60">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--brand-500)]" />
        </span>
      )}
    </div>
  );
}
