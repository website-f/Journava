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

type SavedTrip = { id: string; title: string; destination: string | null; scope: string; created_at: string | null };

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
          onClick={() => void openTrip(t)}
          onDelete={() => void deleteTrip(t)}
        />
      ))}
    </div>
  );
}

function TripCard({
  title,
  subtitle,
  band,
  when,
  optionCount,
  badge,
  loading,
  thumbKey,
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
  onClick: () => void;
  onDelete?: () => void;
}) {
  // Fetch a real, compressed destination photo (cached), falling back to the
  // colour band while it loads or if none is found.
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

  return (
    <div className="surface-card group relative overflow-hidden p-0 transition-colors hover:border-[var(--brand-400)]">
      <button
        onClick={onClick}
        disabled={loading}
        className="block w-full text-left disabled:opacity-70"
      >
        {/* Destination thumbnail — real photo when found, colour band otherwise */}
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
        <div className="p-3">
          {subtitle && <p className="line-clamp-2 text-sm font-medium">{subtitle}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {typeof optionCount === "number" && optionCount > 0 && (
              <Badge>{optionCount} options</Badge>
            )}
            {when && (
              <span className="flex items-center gap-1 text-[0.65rem] text-[var(--muted)]">
                <Clock className="h-3 w-3" /> {when}
              </span>
            )}
          </div>
        </div>
      </button>
      {onDelete && (
        <button
          aria-label="Remove trip"
          onClick={(event) => {
            event.stopPropagation();
            onDelete();
          }}
          className="absolute bottom-2 right-2 grid h-8 w-8 place-items-center rounded-full bg-[var(--surface)]/90 text-[var(--muted)] opacity-0 shadow transition-opacity hover:text-[var(--danger)] group-hover:opacity-100"
        >
          <Trash2 className="h-4 w-4" />
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
