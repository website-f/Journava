import {
  Activity,
  ArrowLeft,
  Bus,
  Building2,
  Calendar,
  CheckCircle2,
  Cloud,
  Compass,
  CreditCard,
  ExternalLink,
  FileCheck2,
  Info,
  Leaf,
  MapPin,
  Plane,
  RotateCcw,
  Save,
  ShieldAlert,
  ShieldCheck,
  ShoppingCart,
  Sparkles,
  ThumbsUp,
  TrendingUp,
  Users,
  Utensils,
  Wallet,
  type IconType,
} from "@/components/ui/icons";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Collapsible, OptionCard, Skeleton } from "@/components/ui";
import { Page, Rail, SectionHeader } from "@/components/layout/Page";
import { AgentTheater } from "@/components/ui/AgentTheater";
import { useAgentStream } from "@/hooks/useAgentStream";
import { Money, CurrencySwitcher } from "@/components/ui/Money";
import { useCurrency } from "@/lib/money";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import { FlightResults } from "@/features/flights/FlightResults";
import { PlaceCard } from "./PlaceCard";
import { PlacesSection } from "./PlacesSection";
import { VideoCarousel } from "@/components/ui/VideoCarousel";
import type { AgentPlanResult, PlanOption, PlanResults, Scope, VideoReview } from "@/lib/types";

/** Per-section label + a recognizable icon, for the jump-bar and headers. */
const SECTION_META: Record<string, { label: string; Icon: IconType }> = {
  summary: { label: "Overview", Icon: Sparkles },
  intelligence: { label: "Intelligence", Icon: TrendingUp },
  flights: { label: "Flights", Icon: Plane },
  hotels: { label: "Stays", Icon: Building2 },
  dining: { label: "Food", Icon: Utensils },
  activities: { label: "Places", Icon: Compass },
  itinerary: { label: "Itinerary", Icon: Calendar },
  budget: { label: "Budget", Icon: Wallet },
  weather: { label: "Weather", Icon: Cloud },
  risk: { label: "Safety", Icon: ShieldAlert },
  transport: { label: "Transport", Icon: Bus },
  visa: { label: "Visa", Icon: FileCheck2 },
  insurance: { label: "Insurance", Icon: ShieldCheck },
  crowd: { label: "Crowds", Icon: Users },
  social: { label: "Social", Icon: ThumbsUp },
  practical: { label: "Practical", Icon: Info },
  shopping: { label: "Shopping", Icon: ShoppingCart },
  payment: { label: "Money", Icon: CreditCard },
  sustainability: { label: "Eco", Icon: Leaf },
  analytics: { label: "Analytics", Icon: Activity },
  concierge: { label: "Concierge", Icon: Sparkles },
};

/**
 * Sticky jump-bar for the results. A full trip stacks a dozen sections; this
 * lets the traveller hop straight to Visa (or back to Flights) instead of
 * scrolling past everything. Each chip carries its section icon; only sections
 * that rendered content get one, and the active chip tracks the scroll
 * position (IntersectionObserver) and auto-scrolls itself into view.
 *
 * It pins BELOW the shell's top bar rather than at `top: 0` — with the document
 * as the scroll container (see AppShell) `top: 0` parked the whole strip
 * underneath the glass header, where it was invisible but still swallowed taps.
 */
function SectionNav({
  containerRef,
  deps,
}: {
  containerRef: React.RefObject<HTMLDivElement | null>;
  deps: unknown;
}) {
  const [items, setItems] = useState<{ id: string; key: string; label: string }[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const els = Array.from(container.querySelectorAll<HTMLElement>("[data-section]")).filter(
      (el) => (el.textContent ?? "").trim().length > 0,
    );
    setItems(
      els.map((el) => {
        const key = el.dataset.section || "";
        return { id: el.id, key, label: SECTION_META[key]?.label || el.dataset.label || key };
      }),
    );
    if (els.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const top = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setActive(top.target.id);
      },
      { rootMargin: "-18% 0px -74% 0px", threshold: 0 },
    );
    els.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [containerRef, deps]);

  // Keep the active chip visible as the page scrolls through sections. Scrolling
  // the strip itself, rather than `scrollIntoView`, because the latter also walks
  // up and nudges the document — which fights the scroll that triggered this.
  useEffect(() => {
    const nav = navRef.current;
    if (!active || !nav) return;
    const chip = nav.querySelector<HTMLElement>(`[data-chip="${active}"]`);
    if (!chip) return;
    nav.scrollTo({
      left: Math.max(0, chip.offsetLeft - (nav.clientWidth - chip.offsetWidth) / 2),
      behavior: "smooth",
    });
  }, [active]);

  if (items.length <= 1) return null;

  return (
    <nav
      ref={navRef}
      className={cn(
        "no-scrollbar sticky z-30 -mx-4 mb-7 flex gap-2 overflow-x-auto px-4 py-3 md:-mx-6 md:px-6",
        "[overscroll-behavior-inline:contain] [scroll-padding-inline:1rem]",
      )}
      style={{
        top: "calc(var(--safe-top) + var(--top-bar))",
        backgroundColor: "color-mix(in srgb, var(--bg) 84%, transparent)",
        backdropFilter: "blur(16px) saturate(170%)",
        WebkitBackdropFilter: "blur(16px) saturate(170%)",
        boxShadow: "inset 0 -1px 0 color-mix(in srgb, var(--text) 8%, transparent)",
      }}
      aria-label="Jump to section"
    >
      {items.map((item) => {
        const Icon = SECTION_META[item.key]?.Icon;
        const isActive = active === item.id;
        return (
          <button
            key={item.id}
            data-chip={item.id}
            type="button"
            aria-current={isActive}
            onClick={() =>
              document.getElementById(item.id)?.scrollIntoView({ behavior: "smooth", block: "start" })
            }
            className={cn(
              "pressable inline-flex shrink-0 items-center gap-1.5 rounded-[var(--r-pill)] px-3.5 py-2",
              "text-[0.75rem] font-semibold whitespace-nowrap",
              isActive
                ? "bg-[var(--brand-500)] text-white shadow-[0_3px_10px_color-mix(in_srgb,var(--brand-500)_40%,transparent)]"
                : "bg-[var(--surface)] text-[var(--muted)] ring-1 ring-inset ring-[var(--border)] hover:text-[var(--text)] hover:ring-[var(--brand-400)]",
            )}
          >
            {Icon && <Icon className="h-4 w-4" weight={isActive ? "fill" : "regular"} />}
            {item.label}
          </button>
        );
      })}
    </nav>
  );
}

/** Pull the top video reviews the research agent attached, by category. */
function videoReviews(results: PlanResults, key: "attractions" | "food"): VideoReview[] {
  const data = results.research?.data as
    | { video_reviews?: Record<string, VideoReview[]> }
    | undefined;
  return data?.video_reviews?.[key] ?? [];
}

/**
 * Renders only the panels the chosen scope produced.
 *
 * This is the other half of scoping: running fewer agents is pointless if the
 * page still renders 12 empty sections. `scope.panels` decides what appears, in
 * the order that scope considers most useful.
 */

/**
 * The live-run banner on the results page. Sections stream in tier-by-tier, so
 * the run keeps going after the first results render — this keeps the Agent
 * Theater on screen (collapsible) so the traveller can watch the 21-agent mesh
 * finish while browsing what's already landed. Same SSE stream as the overlay.
 */
function StreamingMesh() {
  const { events } = useAgentStream();
  const [open, setOpen] = useState(true);
  return (
    <div className="mb-5 overflow-hidden rounded-[var(--r-lg)] border border-[color-mix(in_srgb,var(--brand-400)_38%,transparent)] bg-[color-mix(in_srgb,var(--brand-400)_9%,transparent)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--brand-500)] opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[var(--brand-500)]" />
        </span>
        <p className="min-w-0 flex-1 text-xs leading-snug text-[var(--muted)]">
          Your agents are still working — sections appear the moment each finishes.
        </p>
        <span className="shrink-0 text-[0.7rem] font-semibold text-[var(--brand-600)]">
          {open ? "Hide" : "Watch"}
        </span>
      </button>
      {open && (
        <div className="border-t border-[color-mix(in_srgb,var(--brand-400)_22%,transparent)] px-4 py-3">
          <AgentTheater events={events} />
        </div>
      )}
    </div>
  );
}

export function ScopedResults({
  scope,
  results,
  streaming = false,
  onAskAgain,
  onBack,
  onOpenTrip,
  onReplanCity,
}: {
  scope: Scope;
  results: PlanResults;
  /** True while more sections are still streaming in tier-by-tier. */
  streaming?: boolean;
  onAskAgain: () => void;
  onBack: () => void;
  onOpenTrip: () => void;
  /** Re-run this same scope for a different city in the same country. */
  onReplanCity?: (city: string, country?: string) => void;
}) {
  const panels = (results._scope?.panels?.length ? results._scope.panels : scope.panels) ?? [];
  const agents = results._scope?.agents ?? scope.agents;
  const destination = (results.chief?.data as { destination?: string } | undefined)?.destination;
  const panelsRef = useRef<HTMLDivElement>(null);

  // Default the display currency to the TRAVELLER'S currency (once) — their
  // budget/profile currency, not whatever a crawled fare happened to be priced
  // in. A KLIA→Tokyo fare crawled in USD must show as MYR (converted via live
  // FX by <Money>), never flip the whole page to USD. The switcher still lets
  // them view any currency.
  const setDisplay = useCurrency((s) => s.setDisplay);
  const initedCurrency = useRef(false);
  useEffect(() => {
    if (initedCurrency.current) return;
    const chief = results.chief?.data as Record<string, unknown> | undefined;
    const budgetCur = (results.budget?.data as Record<string, unknown> | undefined)?.currency;
    // Priority: explicit trip budget currency → chief's resolved currency →
    // a flight fare's currency only as a last resort.
    const flightCur = results.flight?.options?.find((o) => o.price_currency)?.price_currency;
    const cur =
      (typeof budgetCur === "string" ? budgetCur : undefined) ??
      (typeof chief?.budget_currency === "string" ? (chief.budget_currency as string) : undefined) ??
      flightCur;
    if (cur) {
      setDisplay(cur.toUpperCase());
      initedCurrency.current = true;
    }
  }, [results, setDisplay]);

  const critic = results.critic?.data as { score?: number; retried?: boolean } | undefined;
  const scopeLabel = (results._scope as { label?: string } | undefined)?.label ?? scope.label;
  const trip = useTripActions(results);
  // The hero already leads with the destination and the chief's summary, so the
  // separate "summary" panel repeated both. Drop it from the section list.
  const bodyPanels = panels.filter((panel) => panel !== "summary");

  return (
    <Page width="lg">
      {/* Utility row. Kept OFF the hero so the currency <Select> renders on the
          page background it was styled for, not on the dark teal panel. */}
      <div className="mb-4 flex items-center gap-1">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          All modes
        </Button>
        <Button variant="ghost" size="sm" onClick={onAskAgain}>
          <RotateCcw className="h-4 w-4" />
          Ask again
        </Button>
        <div className="min-w-0 flex-1" />
        <CurrencySwitcher className="h-9 w-[6.5rem] text-xs" />
      </div>

      <ResultsHero
        destination={destination}
        summary={results.chief?.summary}
        scopeLabel={scopeLabel}
        agentCount={agents.length}
        sectionCount={bodyPanels.length}
        streaming={streaming}
        criticScore={critic?.score}
        criticRetried={critic?.retried}
        trip={trip}
        onOpenTrip={onOpenTrip}
      />

      {streaming && <StreamingMesh />}

      <SectionNav containerRef={panelsRef} deps={results} />

      {onReplanCity && destination && (
        <AltCityStrip destination={destination} onPick={onReplanCity} />
      )}

      {/* space-y-12 (not 8): each section is a distinct topic, and the extra
          whitespace is what lets a dozen of them read as separate cards on a
          phone instead of one continuous wall. */}
      <div ref={panelsRef} className="space-y-12">
        {bodyPanels.map((panel) => (
          <div
            key={panel}
            id={`sec-${panel}`}
            data-section={panel}
            data-label={SECTION_META[panel]?.label ?? panel}
            // Adds to html's scroll-padding-top, clearing both the shell's top
            // bar and the sticky section strip pinned beneath it.
            className="scroll-mt-12"
          >
            <Panel name={panel} results={results} />
          </div>
        ))}
      </div>

      <AddToTripBar trip={trip} onOpenTrip={onOpenTrip} />
    </Page>
  );
}

/**
 * Shared add-to-trip / save state, so the hero CTA and the end-of-page bar are
 * the same action rather than two buttons that can disagree about whether the
 * plan has already been added.
 */
function useTripActions(results: PlanResults) {
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const add = async () => {
    setBusy(true);
    try {
      await api.post("/trip/save", { results });
      // Confirming also records it as a saved TRIP, so the Trips gallery shows
      // only trips the traveller actually added — not every search.
      const dest = (results.chief?.data as { destination?: string } | undefined)?.destination;
      await api
        .post("/saved", { kind: "trip", scope: "full_trip", destination: dest, results })
        .catch(() => {});
      setAdded(true);
      toast.success("Added to your trip — open it any time from Trip.");
    } catch {
      toast.error("Could not add this to your trip.");
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    const dest = (results.chief?.data as { destination?: string } | undefined)?.destination;
    const scope = results.itinerary?.items?.length
      ? "full_trip"
      : results.flight && !results.hotel
        ? "flights_only"
        : (results._scope as { label?: string } | undefined)?.label ?? "result";
    setSaving(true);
    try {
      await api.post("/saved", { scope, destination: dest, results });
      setSaved(true);
      toast.success("Saved — find it under Research → Saved results.");
    } catch {
      toast.error("Couldn't save this result.");
    } finally {
      setSaving(false);
    }
  };

  return { add, save, busy, added, saving, saved };
}

type TripActions = ReturnType<typeof useTripActions>;

const HERO_BTN =
  "pressable inline-flex h-11 items-center justify-center gap-2 rounded-[var(--r-pill)] px-5 text-sm font-semibold disabled:opacity-55 disabled:pointer-events-none";

/**
 * The results hero: a solid deep-teal panel with the destination set large.
 *
 * Solid fill, not a gradient wash — the palette is flat by design, and a
 * gradient here would be the one place in the app that isn't. The single warm
 * accent appears as a 3px rule along the top instead.
 */
function ResultsHero({
  destination,
  summary,
  scopeLabel,
  agentCount,
  sectionCount,
  streaming,
  criticScore,
  criticRetried,
  trip,
  onOpenTrip,
}: {
  destination?: string;
  summary?: string;
  scopeLabel?: string;
  agentCount: number;
  sectionCount: number;
  streaming: boolean;
  criticScore?: number;
  criticRetried?: boolean;
  trip: TripActions;
  onOpenTrip: () => void;
}) {
  const stats: Array<[string, string]> = [
    [String(agentCount), streaming ? "agents running" : "agents ran"],
    [String(sectionCount), sectionCount === 1 ? "section" : "sections"],
  ];
  if (criticScore != null) {
    stats.push([criticScore.toFixed(2), criticRetried ? "critic · re-ran" : "critic score"]);
  }

  return (
    <section className="relative mb-6 overflow-hidden rounded-[var(--r-xl)] bg-[var(--brand-600)] text-white shadow-[var(--shadow-3)]">
      <span aria-hidden className="absolute inset-x-0 top-0 h-[3px] bg-[var(--accent)]" />
      <div className="p-5 pt-6 md:p-8">
        {scopeLabel && (
          <p className="text-[0.66rem] font-semibold uppercase tracking-[0.18em] text-white/55">
            {scopeLabel}
          </p>
        )}
        <h1 className="mt-2 font-[family-name:var(--font-display)] text-[2rem] font-bold leading-[1.05] tracking-[-0.03em] md:text-[2.6rem]">
          {destination || "Your plan"}
        </h1>
        {summary && (
          <p className="mt-3 max-w-[52ch] text-[0.9375rem] leading-relaxed text-white/75">
            {summary}
          </p>
        )}

        <dl className="mt-5 flex flex-wrap gap-2">
          {stats.map(([value, label]) => (
            <div
              key={label}
              className="rounded-[var(--r-pill)] bg-white/10 px-3 py-1.5 ring-1 ring-inset ring-white/15"
            >
              <dt className="sr-only">{label}</dt>
              <dd className="text-[0.72rem] font-semibold">
                <span className="tabular-nums">{value}</span>
                <span className="ml-1.5 font-medium text-white/60">{label}</span>
              </dd>
            </div>
          ))}
        </dl>

        <div className="mt-6 flex flex-wrap gap-2">
          {trip.added ? (
            <button
              type="button"
              onClick={onOpenTrip}
              className={cn(HERO_BTN, "bg-white text-[var(--brand-600)] shadow-[var(--shadow-1)]")}
            >
              Open My Trip
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void trip.add()}
              disabled={trip.busy}
              className={cn(HERO_BTN, "bg-white text-[var(--brand-600)] shadow-[var(--shadow-1)]")}
            >
              <CheckCircle2 className="h-4 w-4" />
              {trip.busy ? "Adding…" : "Add to my trip"}
            </button>
          )}
          <button
            type="button"
            onClick={() => void trip.save()}
            disabled={trip.saving || trip.saved}
            className={cn(HERO_BTN, "bg-white/10 text-white ring-1 ring-inset ring-white/25")}
          >
            <Save className="h-4 w-4" />
            {trip.saved ? "Saved" : trip.saving ? "Saving…" : "Save result"}
          </button>
        </div>
      </div>
    </section>
  );
}

/**
 * "Not set on {city}? Try another." — the agents suggest same-country cities
 * (map-first, else Camofox/LLM), so a traveller who searched a whole country and
 * landed on one city can re-plan a sibling city in one tap, without retyping.
 */
function AltCityStrip({
  destination,
  onPick,
}: {
  destination: string;
  onPick: (city: string, country?: string) => void;
}) {
  const [cities, setCities] = useState<string[] | null>(null);
  const [country, setCountry] = useState<string | undefined>();

  useEffect(() => {
    let live = true;
    api
      .get<{ country?: string; cities?: string[] }>(
        `/plan/nearby-cities?destination=${encodeURIComponent(destination)}`,
      )
      .then((res) => {
        if (!live) return;
        setCountry(res.country);
        setCities((res.cities ?? []).slice(0, 6));
      })
      .catch(() => live && setCities([]));
    return () => {
      live = false;
    };
  }, [destination]);

  if (!cities || cities.length === 0) return null;

  // The city label from the plan may be "Osaka, Japan" — show just the city.
  const here = destination.split(",")[0]?.trim() || destination;

  return (
    <div className="mb-6 rounded-[var(--r-lg)] border border-[var(--border)] bg-[color-mix(in_srgb,var(--accent)_6%,transparent)] p-4">
      <p className="flex items-center gap-1.5 text-sm font-medium">
        <Sparkles className="h-4 w-4 text-[var(--accent)]" />
        Not set on {here}? Re-plan a nearby city
      </p>
      <p className="mt-0.5 text-xs text-[var(--muted)]">
        Same trip, same dates — your agents re-run flights, stays and places for the city you pick.
      </p>
      <div className="mt-2.5 flex flex-wrap gap-2">
        {cities.map((city) => (
          <button
            key={city}
            type="button"
            onClick={() => onPick(city, country)}
            className="inline-flex items-center gap-1 rounded-[var(--r-pill)] border border-[var(--border)] px-3 py-1.5 text-xs font-medium transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
          >
            <MapPin className="h-3.5 w-3.5" />
            {city}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * Bottom-of-results CTA: adopt this whole plan as the traveller's active trip.
 *
 * Shares `useTripActions` with the hero rather than holding its own copy of the
 * add/save state — two independent copies meant scrolling past a plan you had
 * already added still offered to add it again.
 */
function AddToTripBar({ trip, onOpenTrip }: { trip: TripActions; onOpenTrip: () => void }) {
  return (
    <div className="mt-10 flex flex-col items-center gap-2 rounded-[var(--r-xl)] border border-[color-mix(in_srgb,var(--brand-400)_38%,transparent)] bg-[color-mix(in_srgb,var(--brand-400)_8%,transparent)] p-6 text-center">
      <p className="font-[family-name:var(--font-display)] text-base font-semibold">
        Happy with this plan?
      </p>
      <p className="max-w-[42ch] text-xs leading-relaxed text-[var(--muted)]">
        Add it to your trip — your agents keep monitoring flights, weather and safety after.
      </p>
      <div className="mt-2 flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center sm:justify-center">
        {trip.added ? (
          <Button variant="secondary" onClick={onOpenTrip}>
            Open My Trip
          </Button>
        ) : (
          <Button loading={trip.busy} onClick={() => void trip.add()}>
            <CheckCircle2 className="h-4 w-4" />
            Add to my trip
          </Button>
        )}
        <Button
          variant="ghost"
          loading={trip.saving}
          disabled={trip.saved}
          onClick={() => void trip.save()}
        >
          <Save className="h-4 w-4" />
          {trip.saved ? "Saved" : "Save result"}
        </Button>
      </div>
    </div>
  );
}

/** The plan's booking/detail sections, reused by My Trip so the saved trip shows
 *  the full plan (flights, stays, food, places, visa, insurance) — not just the
 *  itinerary/budget/weather cards. */
export function TripExtraPanels({ results }: { results: PlanResults }) {
  const panels = ["flights", "hotels", "activities", "dining", "visa", "insurance"];
  return (
    <div className="space-y-10">
      {panels.map((panel) => (
        <Panel key={panel} name={panel} results={results} />
      ))}
    </div>
  );
}

function Panel({ name, results }: { name: string; results: PlanResults }) {
  const city = (results.chief?.data as { destination?: string } | undefined)?.destination;
  switch (name) {
    case "intelligence":
      return <TravelIntelPanel results={results} />;
    case "flights":
      return results.flight ? <FlightResults result={results.flight} /> : null;
    case "hotels":
      return <OptionsPanel result={results.hotel} title="Stays" icon={Building2} />;
    case "dining":
      return (
        <PlacesSection
          title="Places to eat"
          placesLabel="Restaurants"
          icon={Utensils}
          result={results.research}
          kind="restaurant"
          videos={videoReviews(results, "food")}
          city={city}
        />
      );
    case "activities":
      return (
        <PlacesSection
          title="Places to visit"
          placesLabel="Places"
          icon={Compass}
          result={results.research}
          extra={results.recommendation}
          kind="activity"
          videos={videoReviews(results, "attractions")}
          city={city}
        />
      );
    case "itinerary":
      return <ItineraryPanel result={results.itinerary} />;
    case "budget":
      return <BudgetPanel result={results.budget} />;
    case "weather":
      return <WeatherPanel result={results.weather_risk} />;
    case "risk":
      return <RiskPanel results={results} />;
    case "transport":
      return <DataPanel result={results.transport} title="Getting around" icon={Bus} collapsible />;
    case "visa":
      return <VisaPanel result={results.visa} />;
    case "insurance":
      return <InsurancePanel result={results.insurance} />;
    case "crowd":
      return <DataPanel result={results.crowd} title="Crowds" icon={Users} collapsible />;
    case "social":
      return <SocialPanel result={results.research} />;
    case "practical":
      // Two agents, one section — they're both "things to know on the ground",
      // and splitting them into separate jump-bar entries wasn't worth a chip.
      return (
        <div className="space-y-3">
          <DataPanel result={results.emergency} title="Emergency contacts" icon={ShieldAlert} collapsible />
          <DataPanel result={results.language} title="Language & etiquette" icon={Info} collapsible />
        </div>
      );
    case "shopping":
      return <DataPanel result={results.shopping} title="Shopping" icon={ShoppingCart} collapsible />;
    case "payment":
      return (
        <DataPanel result={results.payment} title="Money & payments" icon={CreditCard} collapsible />
      );
    case "sustainability":
      return <DataPanel result={results.sustainability} title="Sustainability" icon={Leaf} collapsible />;
    case "analytics":
      return <DataPanel result={results.analytics} title="Trip analytics" icon={Activity} collapsible />;
    case "concierge":
      return (
        <DataPanel
          result={results.concierge}
          title="Concierge & reservations"
          icon={Sparkles}
          collapsible
        />
      );
    default:
      return null;
  }
}

interface TravelIntel {
  verdict?: "book_now" | "wait" | "flexible";
  confidence?: "high" | "medium" | "low";
  price_trend?: "rising" | "stable" | "falling";
  book_by?: string;
  demand?: "low" | "moderate" | "high";
  reason?: string;
  cheaper_window?: string | null;
  savings_hint?: string | null;
}

/**
 * Predictive Travel Intelligence — "book now or wait?" (hackathon direction 06,
 * Data & Analytics). An agent reasons over the fare spread, crowd, weather and
 * dates the mesh already gathered and returns a forward-looking call with a
 * confidence and the signals behind it.
 */
function TravelIntelPanel({ results }: { results: PlanResults }) {
  const [intel, setIntel] = useState<TravelIntel | null>(null);
  const [state, setState] = useState<"loading" | "done" | "empty">("loading");

  useEffect(() => {
    let live = true;
    setState("loading");
    api
      .post<{ intel?: TravelIntel; error?: string }>("/intel/predict", { results })
      .then((r) => {
        if (!live) return;
        if (r.intel?.verdict) {
          setIntel(r.intel);
          setState("done");
        } else {
          setState("empty");
        }
      })
      .catch(() => live && setState("empty"));
    return () => {
      live = false;
    };
  }, [results]);

  if (state === "empty") return null;

  const verdictMeta = {
    book_now: { label: "Book now", tone: "success", blurb: "Prices look set to rise — lock it in." },
    wait: { label: "You can wait", tone: "warning", blurb: "Holding a little longer likely pays off." },
    flexible: { label: "You're flexible", tone: "brand", blurb: "Dates are movable — here's the smart play." },
  }[intel?.verdict ?? "flexible"];
  const toneCls: Record<string, string> = {
    success: "border-[var(--success)]/40 bg-[color-mix(in_srgb,var(--success)_10%,transparent)] text-[var(--success)]",
    warning: "border-[var(--warning)]/40 bg-[color-mix(in_srgb,var(--warning)_10%,transparent)] text-[var(--warning)]",
    brand: "border-[var(--brand-500)]/40 bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)] text-[var(--brand-600)]",
  };
  const trendArrow = { rising: "↑", stable: "→", falling: "↓" }[intel?.price_trend ?? "stable"];

  return (
    <section>
      <SectionHeader
        icon={<TrendingUp className="h-[1.15rem] w-[1.15rem]" />}
        title="Travel intelligence"
        hint="Forward-looking read on fares, demand and timing."
        action={
          <span className="rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--accent)_16%,transparent)] px-2 py-1 text-[0.6rem] font-semibold uppercase tracking-[0.1em] text-[var(--accent)]">
            Predictive
          </span>
        }
      />

      {state === "loading" ? (
        <div className="surface-card p-4">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="mt-2 h-4 w-full" />
        </div>
      ) : (
        <div className="space-y-3">
          <div className={cn("flex items-center gap-3 rounded-[var(--r-md)] border p-3", toneCls[verdictMeta.tone])}>
            <TrendingUp className="h-6 w-6 shrink-0" />
            <div className="min-w-0">
              <p className="text-sm font-semibold">
                {verdictMeta.label}
                {intel?.confidence && (
                  <span className="ml-2 text-[0.7rem] font-medium opacity-80">{intel.confidence} confidence</span>
                )}
              </p>
              <p className="mt-0.5 text-xs text-[var(--text)] opacity-80">{intel?.reason || verdictMeta.blurb}</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <ReportTile label="Price trend" value={`${trendArrow} ${intel?.price_trend ?? "—"}`} />
            <ReportTile label="Book by" value={intel?.book_by || "—"} />
            <ReportTile label="Demand" value={intel?.demand ?? "—"} />
            <ReportTile label="Cheaper window" value={intel?.cheaper_window || "these dates"} />
          </div>

          {intel?.savings_hint && (
            <p className="flex items-center gap-1.5 text-xs text-[var(--brand-600)]">
              <Sparkles className="h-3.5 w-3.5" />
              {intel.savings_hint}
            </p>
          )}
        </div>
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
  icon: IconType;
  filter?: (option: PlanOption) => boolean;
  extra?: AgentPlanResult;
}) {
  const own = result?.options ?? [];
  const extras = extra?.options ?? [];
  const options = [...own, ...extras].filter((option) => !filter || filter(option));
  if (options.length === 0) return null;

  return (
    <section>
      <SectionHeader
        icon={<Icon className="h-[1.15rem] w-[1.15rem]" />}
        title={title}
        count={options.length}
        hint={result?.summary}
      />
      {/*
        A rail on phones, a real grid from md up. `<Rail>` owns the gutter maths
        (scroll-padding-inline matched to the negative margin) so a snapped card
        lands flush with the heading above it instead of a gutter to its left.
      */}
      <Rail card="16.5rem" cols={2} colsLg={3} aria-label={title}>
        {options.map((option) => (
          <PlaceCard key={option.id} option={option} />
        ))}
      </Rail>
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
      <SectionHeader
        icon={<Calendar className="h-[1.15rem] w-[1.15rem]" />}
        title="Itinerary"
        count={items.length}
        hint={result?.summary}
      />
      <div className="space-y-5">
        {[...days.entries()]
          .sort(([a], [b]) => a - b)
          .map(([day, dayItems]) => (
            <div key={day} className="surface-card overflow-hidden">
              <div className="flex items-center gap-2 border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--brand-400)_7%,transparent)] px-4 py-2.5">
                <span className="grid h-6 w-6 place-items-center rounded-full bg-[var(--brand-500)] text-[0.65rem] font-bold text-white tabular-nums">
                  {day}
                </span>
                <h4 className="text-[0.8125rem] font-semibold">Day {day}</h4>
                <span className="ml-auto text-[0.7rem] text-[var(--muted)] tabular-nums">
                  {dayItems.length} {dayItems.length === 1 ? "stop" : "stops"}
                </span>
              </div>
              <ol className="space-y-4 px-4 py-4">
                {dayItems.map((item, index) => (
                  <li key={index} className="relative pl-5">
                    {/* The connector stops short on the last row so the timeline
                        ends at the final stop instead of trailing into padding. */}
                    {index < dayItems.length - 1 && (
                      <span
                        aria-hidden
                        className="absolute left-[0.1875rem] top-3 bottom-[-1rem] w-px bg-[var(--border)]"
                      />
                    )}
                    <span
                      aria-hidden
                      className="absolute left-0 top-1.5 h-[0.4375rem] w-[0.4375rem] rounded-full bg-[var(--brand-400)] ring-2 ring-[var(--surface)]"
                    />
                    <p className="text-[0.875rem] font-medium leading-snug">{item.title}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
                      <Badge>{item.kind}</Badge>
                      {item.starts_at && (
                        <span className="tabular-nums">
                          {item.starts_at}
                          {item.ends_at ? ` – ${item.ends_at}` : ""}
                        </span>
                      )}
                      {item.cost_amount != null && (
                        <span className="font-semibold text-[var(--brand-600)]">
                          {item.cost_currency ?? "MYR"}{" "}
                          {Number(item.cost_amount).toLocaleString()}
                        </span>
                      )}
                    </div>
                    {item.reasoning && (
                      <p className="mt-1 text-xs italic leading-relaxed text-[var(--muted)]">
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
      <SectionHeader
        icon={<Wallet className="h-[1.15rem] w-[1.15rem]" />}
        title="Budget"
        action={
          <Badge variant={data.over_budget ? "danger" : "success"}>
            {data.over_budget ? "Over budget" : "On track"}
          </Badge>
        }
      />
      <div className="surface-card space-y-4 p-4">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <p className="font-[family-name:var(--font-display)] text-[1.5rem] font-bold leading-none tracking-[-0.02em]">
            <Money amount={spent} currency={currency} />
          </p>
          {total > 0 && (
            <p className="text-xs text-[var(--muted)] tabular-nums">
              of <Money amount={total} currency={currency} /> · {pct}%
            </p>
          )}
        </div>
        {total > 0 && (
          <div className="h-2.5 overflow-hidden rounded-full bg-[var(--border)]">
            <div
              className="h-full rounded-full transition-[width] duration-[var(--dur-slow)] ease-[var(--ease)]"
              style={{
                width: `${pct}%`,
                backgroundColor: data.over_budget ? "var(--danger)" : "var(--brand-500)",
              }}
            />
          </div>
        )}
        <p className="text-sm leading-relaxed text-[var(--muted)]">{result.summary}</p>
        {data.breakdown && (
          <div className="grid grid-cols-2 gap-2 border-t border-[var(--border)] pt-3 sm:grid-cols-4">
            {(["flights", "hotels_total", "activities", "nights"] as const).map((key) => (
              <div
                key={key}
                className="rounded-[var(--r-sm)] bg-[color-mix(in_srgb,var(--brand-400)_6%,transparent)] p-2.5 text-center"
              >
                <p className="text-[0.6rem] uppercase tracking-[0.08em] text-[var(--muted)]">
                  {key.replace(/_/g, " ")}
                </p>
                <p className="mt-1 text-[0.8125rem] font-semibold tabular-nums">
                  {key === "nights" ? (
                    (data.breakdown?.[key] ?? "—")
                  ) : (
                    <Money amount={data.breakdown?.[key] ?? 0} currency={currency} />
                  )}
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
      <SectionHeader
        icon={<Cloud className="h-[1.15rem] w-[1.15rem]" />}
        title="Weather"
        action={<Badge variant={variant}>{level} risk</Badge>}
      />
      <div className="surface-card p-4">
        <p className="mb-4 text-sm leading-relaxed text-[var(--muted)]">{result.summary}</p>
        {data.forecast && data.forecast.length > 0 && (
          // A rail on phones (7 days never fit three-up without squashing the
          // temperatures), a plain row from md.
          <Rail card="4.5rem" cols={7} colsLg={7} aria-label="Daily forecast">
            {data.forecast.slice(0, 7).map((day) => (
              <div
                key={day.date}
                className="rounded-[var(--r-sm)] bg-[color-mix(in_srgb,var(--brand-400)_7%,transparent)] p-2.5 text-center"
                title={day.description}
              >
                <p className="text-[0.6rem] text-[var(--muted)] tabular-nums">{day.date.slice(5)}</p>
                <p className="mt-1 text-[0.9375rem] font-semibold tabular-nums">{day.high_c}°</p>
                <p className="text-[0.65rem] text-[var(--muted)] tabular-nums">{day.low_c}°</p>
                {day.precipitation_pct >= 60 && (
                  <p className="mt-0.5 text-[0.6rem] font-semibold text-[var(--warning)] tabular-nums">
                    {day.precipitation_pct}%
                  </p>
                )}
              </div>
            ))}
          </Rail>
        )}
      </div>
    </section>
  );
}

interface NewsAlert {
  headline: string;
  severity: "high" | "medium" | "low";
  url?: string;
}

/** Travel safety & alerts: a clear go/no-go verdict, the live news the browser
 *  agent found (war/disaster/unrest), and a quick weather + crowd report. */
function RiskPanel({ results }: { results: PlanResults }) {
  const result = results.risk_advisory;
  if (!result) return null;
  const data = result.data as {
    safety_level?: string;
    verdict?: "clear" | "caution" | "avoid";
    active_threats?: string[];
    safe_months?: string[];
    recommended_action?: string;
    news_checked?: boolean;
    news_alerts?: NewsAlert[];
    news_search_url?: string | null;
    travel_window?: string;
  };
  const level = data.safety_level ?? "unknown";
  const verdict = data.verdict ?? (level === "safe" ? "clear" : level === "dangerous" ? "avoid" : "caution");
  const alerts = data.news_alerts ?? [];

  const meta = {
    clear: { label: "Safe to go", tone: "success", icon: CheckCircle2 },
    caution: { label: "Travel with caution", tone: "warning", icon: ShieldAlert },
    avoid: { label: "Reconsider these dates", tone: "danger", icon: ShieldAlert },
  }[verdict];
  const Icon = meta.icon;

  // Quick report pulled from the sibling agents.
  const weather = results.weather_risk?.data as
    | { risk_level?: string; forecast?: Array<{ high_c: number; low_c: number }> }
    | undefined;
  const crowd = results.crowd?.data as { crowd_level?: string; level?: string } | undefined;
  const temps = weather?.forecast?.[0];

  const toneCls: Record<string, string> = {
    success: "border-[var(--success)]/40 bg-[color-mix(in_srgb,var(--success)_10%,transparent)] text-[var(--success)]",
    warning: "border-[var(--warning)]/40 bg-[color-mix(in_srgb,var(--warning)_10%,transparent)] text-[var(--warning)]",
    danger: "border-[var(--danger)]/40 bg-[color-mix(in_srgb,var(--danger)_10%,transparent)] text-[var(--danger)]",
  };
  const sevCls: Record<string, string> = {
    high: "text-[var(--danger)] bg-[color-mix(in_srgb,var(--danger)_14%,transparent)]",
    medium: "text-[var(--warning)] bg-[color-mix(in_srgb,var(--warning)_16%,transparent)]",
    low: "text-[var(--muted)] bg-[color-mix(in_srgb,var(--muted)_14%,transparent)]",
  };

  return (
    <section>
      <SectionHeader
        icon={<ShieldAlert className="h-[1.15rem] w-[1.15rem]" />}
        title="Travel safety & alerts"
        action={data.travel_window ? <Badge>{data.travel_window}</Badge> : undefined}
      />

      {/* Go / no-go verdict banner */}
      <div className={cn("flex items-center gap-3 rounded-[var(--r-md)] border p-3", toneCls[meta.tone])}>
        <Icon className="h-6 w-6 shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-semibold">{meta.label}</p>
          <p className="mt-0.5 text-xs text-[var(--text)] opacity-80">{result.summary}</p>
        </div>
      </div>

      {/* Quick report */}
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <ReportTile label="Safety" value={level} />
        <ReportTile
          label="Weather"
          value={
            weather?.risk_level
              ? `${weather.risk_level} risk${temps ? ` · ${temps.high_c}°/${temps.low_c}°` : ""}`
              : "—"
          }
        />
        <ReportTile label="Crowds" value={crowd?.crowd_level ?? crowd?.level ?? "—"} />
        <ReportTile
          label="Better months"
          value={(data.safe_months ?? []).slice(0, 3).join(", ") || "any"}
        />
      </div>

      {/* Live news the agent found */}
      <div className="mt-3 surface-card p-4">
        <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <ExternalLink className="h-4 w-4 text-[var(--brand-500)]" />
          Live news check
        </h4>
        {alerts.length > 0 ? (
          <ul className="space-y-2">
            {alerts.map((alert, index) => (
              <li key={index} className="flex items-start gap-2">
                <span
                  className={cn(
                    "mt-0.5 shrink-0 rounded-[var(--r-pill)] px-1.5 py-0.5 text-[0.55rem] font-semibold uppercase",
                    sevCls[alert.severity],
                  )}
                >
                  {alert.severity}
                </span>
                {alert.url ? (
                  <a
                    href={alert.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="min-w-0 flex-1 break-words line-clamp-2 text-xs hover:text-[var(--brand-500)] hover:underline"
                  >
                    {alert.headline}
                  </a>
                ) : (
                  <span className="min-w-0 flex-1 break-words line-clamp-2 text-xs">{alert.headline}</span>
                )}
              </li>
            ))}
          </ul>
        ) : data.news_checked ? (
          <p className="flex items-center gap-2 text-xs text-[var(--success)]">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            No war, disaster or unrest news found for {data.travel_window || "your dates"} — clear to go.
          </p>
        ) : (
          <p className="text-xs text-[var(--muted)]">Live news check unavailable right now.</p>
        )}
        {data.news_search_url && (
          <a
            href={data.news_search_url}
            target="_blank"
            rel="noreferrer noopener"
            className="mt-2 inline-flex items-center gap-1 text-[0.7rem] text-[var(--brand-500)] hover:underline"
          >
            <ExternalLink className="h-3 w-3" />
            See all news
          </a>
        )}
      </div>

      {(data.active_threats ?? []).length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {data.active_threats!.map((threat) => (
            <Badge key={threat} variant="danger">
              {threat}
            </Badge>
          ))}
        </div>
      )}
    </section>
  );
}

function ReportTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface-card p-2.5 text-center">
      <p className="text-[0.6rem] uppercase tracking-wide text-[var(--muted)]">{label}</p>
      <p className="mt-0.5 text-xs font-semibold capitalize">{value}</p>
    </div>
  );
}

/** Visa & entry — leads with a clear required / visa-free verdict. */
/** A labelled list of external links from a section's `data.sources`. Custom
 *  panels (Visa/Insurance) don't get DataPanel's automatic source rendering, so
 *  they use this to surface official / booking / comparison links. */
function SourceLinks({
  sources,
  label = "Official links",
}: {
  sources?: Array<{ title?: string; url: string }>;
  label?: string;
}) {
  if (!sources || sources.length === 0) return null;
  return (
    <div className="border-t border-[var(--border)] pt-2">
      <p className="mb-1 text-[0.65rem] uppercase tracking-wide text-[var(--muted)]">{label}</p>
      <ul className="space-y-1">
        {sources.map((s, i) => (
          <li key={i}>
            <a
              href={s.url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1.5 text-xs text-[var(--brand-500)] hover:underline"
            >
              <ExternalLink className="h-3.5 w-3.5 shrink-0" />
              <span className="min-w-0 truncate">{s.title || s.url}</span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function VisaPanel({ result }: { result?: AgentPlanResult }) {
  if (!result) return null;
  const d = result.data as {
    visa_required?: boolean | null;
    visa_type?: string;
    documents?: string[];
    processing_time?: string;
    max_stay?: string;
    cost?: string;
    sources?: Array<{ title?: string; url: string }>;
  };
  const required = d.visa_required;
  const tone = required === false ? "success" : required === true ? "warning" : "muted";
  const label =
    required === false
      ? "Visa-free — no visa needed"
      : required === true
        ? `Visa required${d.visa_type && d.visa_type !== "unknown" ? ` · ${d.visa_type}` : ""}`
        : "Check visa requirements with the embassy";
  const toneCls: Record<string, string> = {
    success: "border-[var(--success)]/40 bg-[color-mix(in_srgb,var(--success)_10%,transparent)] text-[var(--success)]",
    warning: "border-[var(--warning)]/40 bg-[color-mix(in_srgb,var(--warning)_10%,transparent)] text-[var(--warning)]",
    muted: "border-[var(--border)] bg-[var(--surface)] text-[var(--muted)]",
  };
  const rows: Array<[string, string | undefined]> = [
    ["Processing", d.processing_time],
    ["Max stay", d.max_stay],
    ["Cost", d.cost],
  ];

  return (
    <section>
      <SectionHeader icon={<FileCheck2 className="h-[1.15rem] w-[1.15rem]" />} title="Visa & entry" />
      <div className={cn("flex items-center gap-3 rounded-[var(--r-md)] border p-3", toneCls[tone])}>
        {required === false ? (
          <CheckCircle2 className="h-6 w-6 shrink-0" />
        ) : (
          <FileCheck2 className="h-6 w-6 shrink-0" />
        )}
        <p className="text-sm font-semibold">{label}</p>
      </div>
      <div className="mt-3 surface-card space-y-2 p-4">
        <p className="text-sm text-[var(--muted)]">{result.summary}</p>
        {(d.documents ?? []).length > 0 && (
          <div>
            <p className="mb-1 text-[0.65rem] uppercase tracking-wide text-[var(--muted)]">Documents</p>
            <div className="flex flex-wrap gap-1.5">
              {d.documents!.map((doc) => (
                <Badge key={doc}>{doc}</Badge>
              ))}
            </div>
          </div>
        )}
        {rows.some(([, v]) => v) && (
          <dl className="grid gap-2 pt-1 sm:grid-cols-3">
            {rows
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k}>
                  <dt className="text-[0.6rem] uppercase tracking-wide text-[var(--muted)]">{k}</dt>
                  <dd className="text-xs font-medium">{v}</dd>
                </div>
              ))}
          </dl>
        )}
        {result.warnings.map((w, i) => (
          <p key={i} className="text-xs text-[var(--warning)]">
            {w}
          </p>
        ))}
        <SourceLinks sources={d.sources} label="Verify entry rules" />
      </div>
    </section>
  );
}

/** Travel insurance — recommended coverage + notes. */
function InsurancePanel({ result }: { result?: AgentPlanResult }) {
  if (!result) return null;
  const d = result.data as {
    recommended_coverage?: string[];
    notes?: string;
    providers?: string[];
    sources?: Array<{ title?: string; url: string }>;
  };
  if (!(d.recommended_coverage ?? []).length && !result.summary) return null;

  return (
    <section>
      <SectionHeader
        icon={<ShieldCheck className="h-[1.15rem] w-[1.15rem]" />}
        title="Travel insurance"
      />
      <div className="surface-card space-y-2 p-4">
        <p className="text-sm text-[var(--muted)]">{result.summary}</p>
        {(d.recommended_coverage ?? []).length > 0 && (
          <div>
            <p className="mb-1 text-[0.65rem] uppercase tracking-wide text-[var(--muted)]">
              Recommended coverage
            </p>
            <div className="flex flex-wrap gap-1.5">
              {d.recommended_coverage!.map((c) => (
                <Badge key={c} variant="brand">
                  {c.replace(/_/g, " ")}
                </Badge>
              ))}
            </div>
          </div>
        )}
        {d.notes && <p className="text-xs italic text-[var(--muted)]">{d.notes}</p>}
        {(d.providers ?? []).length > 0 && (
          <p className="text-[0.7rem] text-[var(--muted)]">
            Compare: {d.providers!.join(", ")}
          </p>
        )}
        {result.warnings.map((w, i) => (
          <p key={i} className="text-xs text-[var(--warning)]">
            {w}
          </p>
        ))}
        <SourceLinks sources={d.sources} label="Compare & buy" />
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
    <section>
      <SectionHeader
        icon={<ThumbsUp className="h-[1.15rem] w-[1.15rem]" />}
        title="Social signal"
        hint="What real travellers say, and where sources disagree."
        action={
          signal?.confidence ? (
            <Badge>{signal.confidence} confidence</Badge>
          ) : undefined
        }
      />
      <div className="surface-card p-4">
        {signal?.score != null ? (
          <>
            <div className="flex items-center gap-3">
              <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-[var(--border)]">
                <div
                  className="h-full rounded-full bg-[var(--brand-500)] transition-[width] duration-[var(--dur-slow)]"
                  style={{ width: `${Math.round(signal.score * 100)}%` }}
                />
              </div>
              <span className="font-[family-name:var(--font-display)] text-base font-bold tabular-nums">
                {Math.round(signal.score * 100)}
              </span>
            </div>
            <p className="mt-2 text-xs italic leading-relaxed text-[var(--muted)]">{signal.label}</p>
          </>
        ) : (
          <p className="text-xs text-[var(--muted)]">
            Not enough public signal to score this yet.
          </p>
        )}

        {contradictions.length > 0 && (
          <div className="mt-4 border-t border-[var(--border)] pt-3">
            <p className="mb-2 text-[0.65rem] uppercase tracking-[0.1em] text-[var(--muted)]">
              Sources disagree
            </p>
            <ul className="space-y-2">
              {contradictions.map((entry, index) => (
                <li key={index} className="text-xs leading-relaxed">
                  <span className="font-semibold">{entry.topic}: </span>
                  <span className="text-[var(--muted)]">{entry.claim}</span>
                  {entry.counter_claim && (
                    <>
                      <span className="font-semibold text-[var(--warning)]"> — but </span>
                      <span className="text-[var(--muted)]">{entry.counter_claim}</span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

/**
 * Generic renderer for the advisory agents, whose payloads are free-form.
 *
 * `collapsible` is how a full trip stays readable: the primary sections (flights,
 * stays, itinerary, budget, safety) stay open, while the dozen advisory ones
 * arrive as closed rows showing their summary line, so the page is a scannable
 * list rather than a mile of prose the traveller has to scroll past.
 */
function DataPanel({
  result,
  title,
  icon: Icon,
  collapsible = false,
}: {
  result?: AgentPlanResult;
  title: string;
  icon?: IconType;
  collapsible?: boolean;
}) {
  if (!result) return null;
  const data = result.data ?? {};
  const sources = Array.isArray(data.sources)
    ? (data.sources as Array<{ title?: string; url: string }>)
    : [];
  const videos = Array.isArray(data.videos) ? (data.videos as VideoReview[]) : [];
  const HIDDEN = ["destination", "sources", "videos", "hero_image", "booking_links"];
  const entries = Object.entries(data).filter(
    ([key, value]) =>
      !HIDDEN.includes(key) &&
      value !== null &&
      value !== "" &&
      !(Array.isArray(value) && value.length === 0),
  );
  // Scalars render compactly in a 2-column grid; nested arrays/objects get their
  // own full-width block so a list like shopping "markets" reads as cards, not
  // as a wall of raw JSON.
  const isComplex = (v: unknown) => v !== null && typeof v === "object";
  const simple = entries.filter(([, v]) => !isComplex(v));
  const complex = entries.filter(([, v]) => isComplex(v));

  const body = (
    <div className="space-y-3">
      <p className="text-sm leading-relaxed text-[var(--muted)]">{result.summary}</p>

      {simple.length > 0 && (
        <dl className="grid gap-x-4 gap-y-3 sm:grid-cols-2">
          {simple.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="text-[0.65rem] uppercase tracking-[0.1em] text-[var(--muted)]">
                {key.replace(/_/g, " ")}
              </dt>
              <dd className="mt-0.5 break-words text-[0.8125rem]">{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {complex.map(([key, value]) => (
        <div key={key} className="min-w-0">
          <p className="mb-1.5 text-[0.65rem] uppercase tracking-[0.1em] text-[var(--muted)]">
            {key.replace(/_/g, " ")}
          </p>
          <FieldValue value={value} />
        </div>
      ))}

      {videos.length > 0 && <VideoCarousel videos={videos} />}
      {sources.length > 0 && <SourceLinks sources={sources} label="Sources" />}
      {result.warnings.map((warning, index) => (
        <p key={index} className="text-xs text-[var(--warning)]">
          {warning}
        </p>
      ))}
    </div>
  );

  if (collapsible) {
    return (
      <Collapsible
        title={title}
        icon={Icon ? <Icon className="h-[1.15rem] w-[1.15rem]" /> : undefined}
        summary={result.summary}
      >
        {body}
      </Collapsible>
    );
  }

  return (
    <section>
      <SectionHeader
        icon={Icon ? <Icon className="h-[1.15rem] w-[1.15rem]" /> : undefined}
        title={title}
      />
      <div className="surface-card p-4">{body}</div>
    </section>
  );
}

/** Render a free-form agent value: a list of objects becomes cards, a list of
 *  scalars becomes chips, an object becomes labelled fields, a scalar is text. */
function FieldValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    const objs = value.filter((v) => v !== null && typeof v === "object" && !Array.isArray(v));
    if (objs.length === value.length && objs.length > 0) {
      return (
        <ul className="space-y-1.5">
          {objs.map((item, i) => (
            <li key={i} className="rounded-[var(--r-sm)] bg-[var(--bg)] p-2">
              <ObjectCard obj={item as Record<string, unknown>} />
            </li>
          ))}
        </ul>
      );
    }
    return (
      <div className="flex flex-wrap gap-1">
        {value.map((v, i) => (
          <span
            key={i}
            className="rounded-[var(--r-pill)] bg-[var(--bg)] px-2 py-0.5 text-[0.7rem] break-words"
          >
            {typeof v === "object" ? JSON.stringify(v) : String(v)}
          </span>
        ))}
      </div>
    );
  }
  if (value !== null && typeof value === "object") {
    return (
      <div className="rounded-[var(--r-sm)] bg-[var(--bg)] p-2">
        <ObjectCard obj={value as Record<string, unknown>} />
      </div>
    );
  }
  return <span className="break-words text-xs">{String(value)}</span>;
}

/** One object rendered as an optional bold name + a row of labelled fields. */
function ObjectCard({ obj }: { obj: Record<string, unknown> }) {
  const entries = Object.entries(obj).filter(
    ([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0),
  );
  const nameKey = ["name", "title", "label", "mode", "primary"].find(
    (k) => typeof obj[k] === "string" && obj[k],
  );
  const name = nameKey ? String(obj[nameKey]) : null;
  const rest = entries.filter(([k]) => k !== nameKey);
  return (
    <div className="min-w-0">
      {name && <p className="break-words text-xs font-medium">{name}</p>}
      {rest.length > 0 && (
        <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[0.7rem] text-[var(--muted)]">
          {rest.map(([k, v]) => (
            <span key={k} className="break-words">
              <span className="uppercase tracking-wide opacity-70">{k.replace(/_/g, " ")}</span>{" "}
              {typeof v === "object" ? JSON.stringify(v) : String(v)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export { OptionCard };
