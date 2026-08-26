import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ExternalLink,
  Info,
  Plane,
  ShoppingCart,
} from "@/components/ui/icons";
import { Badge, Button, NumberField, Select } from "@/components/ui";
import { Rail } from "@/components/layout/Page";
import { Money } from "@/components/ui/Money";
import { OtaLinks } from "@/components/ui/OtaLinks";
import { SourceTrustRow } from "@/components/ui/SourceBadge";
import { cn } from "@/lib/cn";
import type { AgentPlanResult, PlanOption } from "@/lib/types";
import { BookingDialog } from "./BookingDialog";

/**
 * Flight results, grouped by source.
 *
 * Atlas first because those are the only fares that can actually be booked, then
 * research and simulated ones, each labelled. The grouping is the point: it makes
 * "bookable fare" and "price seen on a page" visually distinct instead of
 * interleaving them into one list that implies they are equivalent.
 */

const SOURCE_GROUPS: Array<{
  key: string;
  match: (option: PlanOption) => boolean;
  title: string;
  blurb: string;
}> = [
  {
    key: "atlas",
    match: (option) => option.source === "atlas",
    title: "Bookable — Atlas",
    blurb: "Live inventory. Prices are re-confirmed by the booking API before purchase.",
  },
  {
    key: "camofox",
    match: (option) => option.source === "camofox" || option.source === "research",
    title: "Advertised — Camofox research",
    blurb:
      "Fares the browser agent read on public pages. Not held — open the source link to confirm.",
  },
  {
    key: "amadeus",
    match: (option) => option.source === "amadeus",
    title: "Reference — Amadeus",
    blurb: "Test-environment inventory, useful for comparison only.",
  },
  {
    key: "other",
    match: (option) => option.source === "llm" || option.source === "mock" || !option.source,
    title: "Simulated",
    blurb:
      "No live source answered, so the model produced realistic examples. Configure Atlas in the API Vault for real fares.",
  },
];

const RANKING_LABELS: Record<string, string> = {
  cheapest: "Cheapest",
  cheapest_with_baggage: "Cheapest with baggage",
  best_value: "Best value",
  best_time: "Fastest",
};

type StopsFilter = "any" | "direct" | "max1";
type SortMode = "relevance" | "cheapest" | "fastest";
type SourceFilter = "all" | "atlas" | "camofox" | "amadeus" | "sim";

const SOURCE_MATCH: Record<SourceFilter, (o: PlanOption) => boolean> = {
  all: () => true,
  atlas: (o) => o.source === "atlas",
  camofox: (o) => o.source === "camofox" || o.source === "research",
  amadeus: (o) => o.source === "amadeus",
  sim: (o) => o.source === "llm" || o.source === "mock" || !o.source,
};

export function FlightResults({ result }: { result: AgentPlanResult }) {
  const [booking, setBooking] = useState<PlanOption | null>(null);

  // Post-search filters (applied client-side over the returned options).
  const [maxBudget, setMaxBudget] = useState<number | null>(null);
  const [stops, setStops] = useState<StopsFilter>("any");
  const [onlyBookable, setOnlyBookable] = useState(false);
  const [sort, setSort] = useState<SortMode>("relevance");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");

  const options = result.options ?? [];
  const ranking = (result.data?.ranking ?? {}) as Record<string, string | null>;
  const sources = (result.data?.sources ?? {}) as Record<
    string,
    { count?: number; status?: string; pages_read?: string[] }
  >;
  const route = (result.data?.route ?? {}) as {
    origin?: string;
    destination?: string;
    depart?: string;
  };
  const commissionSaved = (result.data?.commission_saved ?? null) as
    | { amount: number; rate_pct: number; on_fare: number; currency: string }
    | null;

  /** offer id → which ranking bucket(s) it won. */
  const badgesFor = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const [bucket, id] of Object.entries(ranking)) {
      if (!id) continue;
      map.set(id, [...(map.get(id) ?? []), RANKING_LABELS[bucket] ?? bucket]);
    }
    return map;
  }, [ranking]);

  const stopsOf = (o: PlanOption) => Number((o.raw as { stops?: number })?.stops ?? 0);
  const durationOf = (o: PlanOption) => Number((o.raw as { duration_hours?: number })?.duration_hours ?? 99);

  const filtered = useMemo(() => {
    let list = options.slice();
    if (sourceFilter !== "all") list = list.filter(SOURCE_MATCH[sourceFilter]);
    if (onlyBookable) list = list.filter((o) => o.bookable);
    if (maxBudget != null) {
      // A budget filter is about price, so unpriced link cards drop out.
      list = list.filter((o) => o.price_amount != null && Number(o.price_amount) <= maxBudget);
    }
    if (stops !== "any") {
      list = list.filter((o) => (stops === "direct" ? stopsOf(o) === 0 : stopsOf(o) <= 1));
    }
    if (sort === "cheapest") {
      list.sort((a, b) => (a.price_amount ?? Infinity) - (b.price_amount ?? Infinity));
    } else if (sort === "fastest") {
      list.sort((a, b) => durationOf(a) - durationOf(b));
    }
    return list;
  }, [options, sourceFilter, onlyBookable, maxBudget, stops, sort]);

  const groups = SOURCE_GROUPS.map((group) => ({
    ...group,
    options: filtered.filter(group.match),
  })).filter((group) => group.options.length > 0);

  // How many the search returned per source — powers the Source dropdown labels.
  const sourceCounts = useMemo(() => {
    const count = (f: SourceFilter) => options.filter(SOURCE_MATCH[f]).length;
    return { atlas: count("atlas"), camofox: count("camofox"), amadeus: count("amadeus"), sim: count("sim") };
  }, [options]);

  const filtersActive =
    sourceFilter !== "all" || onlyBookable || maxBudget != null || stops !== "any" || sort !== "relevance";
  const resetFilters = () => {
    setSourceFilter("all");
    setOnlyBookable(false);
    setMaxBudget(null);
    setStops("any");
    setSort("relevance");
  };

  const pagesRead = sources.camofox?.pages_read ?? [];

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-center gap-2">
        <Plane className="h-5 w-5 text-[var(--brand-500)]" />
        <h3 className="text-lg font-semibold">
          Flights
          {route.origin && route.destination && (
            <span className="ml-2 font-normal text-[var(--muted)]">
              {route.origin} → {route.destination}
              {route.depart && route.depart !== "flexible" && ` · ${route.depart}`}
            </span>
          )}
        </h3>
        <Badge variant="brand">
          {filtersActive ? `${filtered.length}/${options.length}` : options.length}
        </Badge>
      </header>

      <p className="text-sm text-[var(--muted)]">{result.summary}</p>

      {/* Bypass-OTA hook: the ~10% OTA commission avoided by booking direct. */}
      {commissionSaved && commissionSaved.amount > 0 && (
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 rounded-[var(--r-md)] border border-[var(--success)]/40 bg-[color-mix(in_srgb,var(--success)_10%,transparent)] px-3 py-2 text-sm">
          <span className="font-semibold text-[var(--success)]">
            Book direct — save ~
            <Money amount={commissionSaved.amount} currency={commissionSaved.currency} />
          </span>
          <span className="text-[var(--muted)]">
            per ticket vs a ~{commissionSaved.rate_pct}% OTA commission. No middleman markup.
          </span>
        </div>
      )}

      {/* What each source contributed — the reconciliation, made visible. */}
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(sources).map(([name, info]) => (
          <Badge key={name} variant={info.count ? "brand" : "default"}>
            {name}: {info.count ?? 0}
            {info.status && info.status !== "ok" ? ` (${info.status})` : ""}
          </Badge>
        ))}
      </div>

      {/* Post-search filters — narrow the results by budget, stops and more. */}
      {options.length > 0 && (
        <div className="surface-card flex flex-wrap items-end gap-3 p-3">
          <label className="block">
            <span className="mb-1 block text-[0.65rem] font-medium text-[var(--muted)]">
              Max budget
            </span>
            <div className="w-28">
              <NumberField
                min={0}
                placeholder="any"
                value={maxBudget}
                onValueChange={setMaxBudget}
                aria-label="Maximum budget"
              />
            </div>
          </label>
          <label className="block">
            <span className="mb-1 block text-[0.65rem] font-medium text-[var(--muted)]">Source</span>
            <div className="w-40">
              <Select
                value={sourceFilter}
                onValueChange={(v) => setSourceFilter(v as SourceFilter)}
                options={[
                  { value: "all", label: "All sources" },
                  { value: "atlas", label: `Atlas Sandbox (${sourceCounts.atlas})` },
                  { value: "camofox", label: `Camofox (${sourceCounts.camofox})` },
                  { value: "amadeus", label: `Amadeus (${sourceCounts.amadeus})` },
                  { value: "sim", label: `Simulated (${sourceCounts.sim})` },
                ]}
                aria-label="Filter by source"
              />
            </div>
          </label>
          <label className="block">
            <span className="mb-1 block text-[0.65rem] font-medium text-[var(--muted)]">Stops</span>
            <div className="w-36">
              <Select
                value={stops}
                onValueChange={(v) => setStops(v as StopsFilter)}
                options={[
                  { value: "any", label: "Any" },
                  { value: "direct", label: "Direct only" },
                  { value: "max1", label: "Up to 1 stop" },
                ]}
                aria-label="Stops"
              />
            </div>
          </label>
          <label className="block">
            <span className="mb-1 block text-[0.65rem] font-medium text-[var(--muted)]">Sort by</span>
            <div className="w-36">
              <Select
                value={sort}
                onValueChange={(v) => setSort(v as SortMode)}
                options={[
                  { value: "relevance", label: "Recommended" },
                  { value: "cheapest", label: "Cheapest" },
                  { value: "fastest", label: "Fastest" },
                ]}
                aria-label="Sort by"
              />
            </div>
          </label>
          <Button
            variant={onlyBookable ? undefined : "secondary"}
            size="sm"
            onClick={() => setOnlyBookable((v) => !v)}
          >
            Bookable only
          </Button>
          {filtersActive && (
            <Button variant="ghost" size="sm" onClick={resetFilters}>
              Reset
            </Button>
          )}
          <span className="ml-auto self-center text-xs text-[var(--muted)]">
            Showing {filtered.length} of {options.length}
          </span>
        </div>
      )}

      {result.warnings?.length > 0 && (
        <ul className="surface-card space-y-1.5 p-3">
          {result.warnings.map((warning, index) => (
            <li key={index} className="flex items-start gap-2 text-xs text-[var(--warning)]">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {warning}
            </li>
          ))}
        </ul>
      )}

      {groups.map((group) => (
        <div key={group.key}>
          <div className="mb-3">
            <h4 className="text-[0.9375rem] font-semibold tracking-[-0.01em]">{group.title}</h4>
            <p className="mt-0.5 text-xs text-[var(--muted)]">{group.blurb}</p>
          </div>
          {/* Rail on phones, 2-up grid from md — same primitive as Stays/Food/Places
              so every card strip in the app snaps and aligns identically. */}
          <Rail card="17rem" cols={2} colsLg={2} aria-label={group.title}>
            {group.options.map((option, index) => (
              <FlightCard
                key={option.id}
                option={option}
                index={index}
                badges={badgesFor.get(option.id) ?? []}
                onBook={() => setBooking(option)}
              />
            ))}
          </Rail>
        </div>
      ))}

      {groups.length === 0 && options.length > 0 && (
        <div className="surface-card p-6 text-center text-sm text-[var(--muted)]">
          No flights match these filters.{" "}
          <button onClick={resetFilters} className="text-[var(--brand-500)] hover:underline">
            Reset filters
          </button>
        </div>
      )}

      {/* Every page the research agent actually read. */}
      {pagesRead.length > 0 && (
        <div className="surface-card p-4">
          <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <ExternalLink className="h-4 w-4 text-[var(--brand-500)]" />
            Pages Camofox read ({pagesRead.length})
          </h4>
          <ul className="space-y-1">
            {pagesRead.map((url) => (
              <li key={url} className="min-w-0">
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="block truncate text-xs text-[var(--brand-500)] hover:underline"
                  title={url}
                >
                  {url}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {booking && (
        <BookingDialog
          option={booking}
          route={route}
          onClose={() => setBooking(null)}
        />
      )}
    </section>
  );
}

function FlightCard({
  option,
  index,
  badges,
  onBook,
}: {
  option: PlanOption;
  index: number;
  badges: string[];
  onBook: () => void;
}) {
  const raw = (option.raw ?? {}) as {
    stops?: number;
    duration_hours?: number;
    departure_time?: string;
    arrival_time?: string;
    carriers?: string[];
    flight_numbers?: string[];
    preference_notes?: string[];
    price_status?: string;
    ota_links?: { name: string; url: string }[];
  };
  const notes = raw.preference_notes ?? [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04, duration: 0.24 }}
      className={cn(
        "surface-card flex flex-col p-4",
        option.bookable && "border-[var(--success)]/40",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{option.title}</p>
          <p className="mt-0.5 text-xs text-[var(--muted)]">{option.provider}</p>
        </div>
        {option.price_amount != null && (
          <div className="shrink-0 text-right">
            <p className="font-[family-name:var(--font-display)] text-lg font-semibold">
              <Money amount={option.price_amount} currency={option.price_currency} />
            </p>
          </div>
        )}
      </div>

      {badges.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {badges.map((badge) => (
            <Badge key={badge} variant="brand">
              {badge}
            </Badge>
          ))}
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
        {raw.stops != null && <span>{raw.stops === 0 ? "Direct" : `${raw.stops} stop`}</span>}
        {raw.duration_hours != null && <span>· {raw.duration_hours}h</span>}
        {raw.departure_time && <span>· dep {formatTime(raw.departure_time)}</span>}
        {raw.arrival_time && <span>· arr {formatTime(raw.arrival_time)}</span>}
        {raw.flight_numbers?.length ? <span>· {raw.flight_numbers.join(", ")}</span> : null}
      </div>

      {option.reasoning && (
        <p className="mt-2 text-xs italic text-[var(--muted)]">{option.reasoning}</p>
      )}

      {notes.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {notes.map((note) => (
            <li key={note} className="flex items-start gap-1 text-[0.65rem] text-[var(--warning)]">
              <Info className="mt-0.5 h-3 w-3 shrink-0" />
              {note}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 border-t border-[var(--border)] pt-2.5">
        <SourceTrustRow option={option} />
      </div>

      <div className="mt-3 flex items-center gap-2">
        {option.bookable ? (
          <Button size="sm" onClick={onBook}>
            <ShoppingCart className="h-4 w-4" />
            Simulate purchase
          </Button>
        ) : option.source_url ? (
          <Button asChild variant="secondary" size="sm">
            <a href={option.source_url} target="_blank" rel="noreferrer noopener">
              <ExternalLink className="h-4 w-4" />
              Open source page
            </a>
          </Button>
        ) : (
          <span
            className="text-[0.65rem] text-[var(--muted)]"
            title="Only Atlas fares can be carried into a booking flow"
          >
            Not bookable from this source
          </span>
        )}
      </div>

      <OtaLinks links={raw.ota_links} label="Compare fares" />
    </motion.div>
  );
}

function formatTime(value: string): string {
  // Atlas returns ISO-ish strings; show just the clock time when we can.
  const match = /(\d{1,2}:\d{2})/.exec(value);
  return match ? match[1] : value;
}
