import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Compass, Globe, ShieldAlert, Newspaper, ThumbsUp, ThumbsDown,
  TrendingUp, GitCompareArrows, BadgeCheck, ShieldQuestion,
} from "@/components/ui/icons";
import { Button, EmptyState, OptionCard, Tabs, TabsList, TabsTrigger, TabsContent, Badge, Skeleton } from "@/components/ui";
import type { ItineraryItem, PlanOption } from "@/stores/planStore";
import { useActiveTrip } from "@/hooks/useActiveTrip";
import { recordOptionOutcome, recordOutcome } from "@/lib/outcomes";
import { KnowledgeLibrary } from "./KnowledgeLibrary";

type SocialSignal = {
  score: number | null;
  label: string;
  confidence: string;
  basis: Record<string, number>;
};

type Contradiction = {
  topic: string;
  claim: string;
  counter_claim: string;
  sources: string;
};

/**
 * Research Board (spec §3.2). Tabbed destination intelligence — Flights, Hotels,
 * Itinerary, and Intelligence. Each pick shows reasoning ("Why this?").
 */
export function ResearchBoard() {
  return (
    <div className="mx-auto w-full max-w-6xl">
      <Tabs defaultValue="knowledge">
        <TabsList className="flex-wrap">
          <TabsTrigger value="knowledge">
            <BadgeCheck className="h-4 w-4" /> Knowledge library
          </TabsTrigger>
          <TabsTrigger value="trip">
            <Compass className="h-4 w-4" /> This trip
          </TabsTrigger>
        </TabsList>
        <TabsContent value="knowledge">
          <KnowledgeLibrary />
        </TabsContent>
        <TabsContent value="trip">
          <TripResearch />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function TripResearch() {
  // Hydrate from the backend so a reload or a deep link still shows the active
  // trip, instead of an empty state the store happens not to know about.
  const { results, loading } = useActiveTrip();

  const flights = results?.flight?.options ?? [];
  const hotels = results?.hotel?.options ?? [];
  const itinerary = results?.itinerary?.items ?? [];
  const weatherSummary = results?.weather_risk?.summary;
  const researchSummary = results?.research?.summary;

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-6xl">
        <ResearchHeader />
        <div className="space-y-3">
          <Skeleton className="h-10 w-full" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-32 w-full" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!results) {
    return (
      <div className="mx-auto w-full max-w-6xl">
        <ResearchHeader />
        <div className="mt-12">
          <EmptyState
            icon={<Compass className="h-10 w-10" />}
            title="No research runs yet"
            description="Kick off a trip from the Command Center — agents will publish their findings here."
            action={
              <Button asChild variant="secondary">
                <Link to="/">Open Command Center</Link>
              </Button>
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl">
      <ResearchHeader />

      <Tabs defaultValue="flights">
        <TabsList className="flex-wrap">
          <TabsTrigger value="flights">
            Flights <Badge variant="brand">{flights.length}</Badge>
          </TabsTrigger>
          <TabsTrigger value="hotels">
            Hotels <Badge variant="brand">{hotels.length}</Badge>
          </TabsTrigger>
          <TabsTrigger value="itinerary">
            Itinerary <Badge variant="brand">{itinerary.length}</Badge>
          </TabsTrigger>
          <TabsTrigger value="intelligence">Intelligence</TabsTrigger>
        </TabsList>

        <TabsContent value="flights">
          {flights.length === 0 ? (
            <p className="text-sm text-[var(--muted)] py-6">No flight options yet.</p>
          ) : (
            <PagedOptionCards items={flights} label="flight options" />
          )}
        </TabsContent>

        <TabsContent value="hotels">
          {hotels.length === 0 ? (
            <p className="text-sm text-[var(--muted)] py-6">No hotel options yet.</p>
          ) : (
            <PagedOptionCards items={hotels} label="hotel options" />
          )}
        </TabsContent>

        <TabsContent value="itinerary">
          {itinerary.length === 0 ? (
            <p className="text-sm text-[var(--muted)] py-6">No itinerary assembled yet.</p>
          ) : (
            <ItineraryTimeline items={itinerary} />
          )}
        </TabsContent>

        <TabsContent value="intelligence">
          <div className="space-y-4 py-4">
            {/* Research Summary */}
            {researchSummary && (
              <div className="surface-card p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Globe className="h-4 w-4 text-[var(--brand-500)]" />
                  <h4 className="text-sm font-semibold">Research Intelligence</h4>
                </div>
                <p className="text-xs text-[var(--muted)] leading-relaxed">{researchSummary}</p>
                {/* Sources crawled */}
                {Boolean(results?.research?.data?.sources_crawled) && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {((results.research.data.sources_crawled as string[]) ?? []).map((src: string) => (
                      <Badge key={src} variant="brand">{src}</Badge>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Weather & Risk with GDELT */}
            {results?.weather_risk && (
              <div className="surface-card p-4">
                <div className="flex items-center gap-2 mb-2">
                  <ShieldAlert className="h-4 w-4 text-[var(--warning)]" />
                  <h4 className="text-sm font-semibold">Weather & Risk</h4>
                  {Boolean(results.weather_risk.data?.risk_level) && (
                    <Badge variant={String(results.weather_risk.data.risk_level) === "high" ? "danger" : String(results.weather_risk.data.risk_level) === "medium" ? "warning" : "success"}>
                      {String(results.weather_risk.data.risk_level)} risk
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-[var(--muted)] mb-2">{weatherSummary}</p>
                {/* GDELT events */}
                {Boolean(results.weather_risk.data?.gdelt) && (
                  <div className="mt-3 pt-3 border-t border-[var(--border)]">
                    <div className="flex items-center gap-1.5 mb-2">
                      <Newspaper className="h-3.5 w-3.5 text-[var(--muted)]" />
                      <span className="text-xs font-medium text-[var(--muted)]">GDELT Global Events</span>
                    </div>
                    {((results.weather_risk.data.gdelt as Record<string, unknown>).active_threats as string[])?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mb-2">
                        {((results.weather_risk.data.gdelt as Record<string, unknown>).active_threats as string[]).map((t: string) => (
                          <Badge key={t} variant="danger">{t}</Badge>
                        ))}
                      </div>
                    )}
                    {((results.weather_risk.data.gdelt as Record<string, unknown>).recent_events as Array<{ title: string; source: string }>)?.slice(0, 3).map((ev: { title: string; source: string }, i: number) => (
                      <p key={i} className="text-[0.65rem] text-[var(--muted)] leading-relaxed">
                        • {ev.title} <span className="italic">({ev.source})</span>
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Social Signal + contradictions (§3.2) */}
            <SocialSignalCard
              signal={results?.research?.data?.social_signal as SocialSignal | undefined}
              contradictions={
                (results?.research?.data?.contradictions as Contradiction[] | undefined) ?? []
              }
            />

            {/* Dining — halal verification */}
            {(results?.research?.options ?? []).some((o) => o.kind === "restaurant") && (
              <div className="surface-card p-4">
                <h4 className="text-sm font-semibold mb-1">Dining — Halal Verification</h4>
                <p className="text-[0.65rem] text-[var(--muted)] mb-3">
                  Labels are re-derived from JAKIM / MUIS / HalalTrip. A claim no
                  certification body corroborates is shown downgraded, never as certified.
                </p>
                <PagedRows
                  items={results.research.options.filter((o) => o.kind === "restaurant")}
                  label="halal-checked places"
                  render={(opt) => <DiningRow key={opt.id} option={opt} />}
                />
                {(results.research.warnings ?? []).length > 0 && (
                  <ul className="mt-3 space-y-1 border-t border-[var(--border)] pt-2">
                    {results.research.warnings.map((w, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-[0.65rem] text-[var(--warning)]">
                        <ShieldQuestion className="h-3 w-3 shrink-0 mt-0.5" />
                        {w}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {/* Attractions with reasoning */}
            {(results?.research?.options ?? []).some((o) => o.kind === "activity") && (
              <div className="surface-card p-4">
                <h4 className="text-sm font-semibold mb-3">Attractions — Why Journava Chose These</h4>
                <PagedRows
                  items={results.research.options.filter((o) => o.kind === "activity")}
                  label="attractions"
                  render={(opt) => <AttractionRow key={opt.id} option={opt} />}
                />
              </div>
            )}

            {/* Outcome feedback — feeds the §7 ③ flywheel */}
            {(researchSummary || (results?.research?.options ?? []).length > 0) && (
              <ResearchFeedback destination={researchSummary ?? "research"} />
            )}

            {!weatherSummary && !researchSummary && !results?.research?.options?.length && (
              <p className="text-sm text-[var(--muted)] py-6">
                Kick off a trip from the Command Center — intelligence data arrives automatically.
              </p>
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Sub-components
// --------------------------------------------------------------------------- //

// --------------------------------------------------------------------------- //
// Pagination — research runs can be data-heavy, so grids/lists page rather than
// rendering hundreds of cards at once.
// --------------------------------------------------------------------------- //

function Pager({
  page,
  pages,
  setPage,
  total,
  label,
}: {
  page: number;
  pages: number;
  setPage: (n: number) => void;
  total: number;
  label: string;
}) {
  return (
    <div className="mt-4 flex items-center justify-between">
      <span className="text-[0.65rem] text-[var(--muted)]">
        {total} {label}
      </span>
      {pages > 1 && (
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
            Prev
          </Button>
          <span className="px-1 text-xs tabular-nums text-[var(--muted)]">
            {page + 1} / {pages}
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={page >= pages - 1}
            onClick={() => setPage(page + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}

function PagedOptionCards({
  items,
  label,
  pageSize = 9,
}: {
  items: PlanOption[];
  label: string;
  pageSize?: number;
}) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(items.length / pageSize));
  const p = Math.min(page, pages - 1);
  const slice = items.slice(p * pageSize, p * pageSize + pageSize);
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {slice.map((opt) => (
          <OptionCard key={opt.id} option={opt} />
        ))}
      </div>
      <Pager page={p} pages={pages} setPage={setPage} total={items.length} label={label} />
    </>
  );
}

function PagedRows<T extends { id: string }>({
  items,
  render,
  label,
  pageSize = 6,
}: {
  items: T[];
  render: (item: T) => ReactNode;
  label: string;
  pageSize?: number;
}) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(items.length / pageSize));
  const p = Math.min(page, pages - 1);
  const slice = items.slice(p * pageSize, p * pageSize + pageSize);
  return (
    <>
      <div className="space-y-2">{slice.map(render)}</div>
      <Pager page={p} pages={pages} setPage={setPage} total={items.length} label={label} />
    </>
  );
}

function ResearchHeader() {
  return (
    <header className="pt-2 pb-6">
      <h2 className="font-[family-name:var(--font-display)] text-2xl tracking-tight">
        Research Board
      </h2>
      <p className="mt-1 text-sm text-[var(--muted)]">
        Destination intelligence — not a chat blob. Each pick shows the reasoning.
      </p>
    </header>
  );
}

/**
 * Social Signal + contradiction detection (§3.2).
 *
 * The score is labelled Journava-derived on the card itself, because a bare
 * number next to a place name reads as a rating no matter what the docs say.
 */
function SocialSignalCard({
  signal,
  contradictions,
}: {
  signal?: SocialSignal;
  contradictions: Contradiction[];
}) {
  if (!signal && contradictions.length === 0) return null;

  const score = signal?.score ?? null;
  const pct = score != null ? Math.round(score * 100) : null;

  return (
    <div className="surface-card p-4">
      <div className="flex items-center gap-2 mb-2">
        <TrendingUp className="h-4 w-4 text-[var(--brand-500)]" />
        <h4 className="text-sm font-semibold">Social Signal</h4>
        {signal?.confidence && (
          <Badge variant={signal.confidence === "medium" ? "info" : "warning"}>
            {signal.confidence} confidence
          </Badge>
        )}
      </div>

      {pct != null ? (
        <>
          <div className="flex items-center gap-3">
            <div className="h-2 flex-1 rounded-full bg-[var(--border)] overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-[var(--brand-500)] to-[var(--accent)] transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="text-sm font-semibold tabular-nums">{pct}</span>
          </div>
          <p className="mt-1.5 text-[0.65rem] text-[var(--muted)] italic">
            {signal?.label}
          </p>
          {signal?.basis && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {Object.entries(signal.basis)
                .filter(([, v]) => v > 0)
                .map(([key, value]) => (
                  <Badge key={key}>
                    {key.replace(/_/g, " ")}: {value.toLocaleString()}
                  </Badge>
                ))}
            </div>
          )}
        </>
      ) : (
        <p className="text-xs text-[var(--muted)]">
          Not enough public signal to score this destination yet.
        </p>
      )}

      {contradictions.length > 0 && (
        <div className="mt-3 pt-3 border-t border-[var(--border)]">
          <div className="flex items-center gap-1.5 mb-2">
            <GitCompareArrows className="h-3.5 w-3.5 text-[var(--warning)]" />
            <span className="text-xs font-medium">
              Sources disagree ({contradictions.length})
            </span>
          </div>
          <ul className="space-y-2">
            {contradictions.map((c, i) => (
              <li key={i} className="text-[0.65rem] leading-relaxed">
                <span className="font-medium">{c.topic}: </span>
                <span className="text-[var(--muted)]">{c.claim}</span>
                {c.counter_claim && (
                  <>
                    <span className="text-[var(--warning)] font-medium"> — but </span>
                    <span className="text-[var(--muted)]">{c.counter_claim}</span>
                  </>
                )}
                {c.sources && (
                  <span className="text-[var(--muted)] italic"> ({c.sources})</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

const HALAL_LABEL: Record<string, { text: string; variant: "success" | "info" | "warning" }> = {
  certified: { text: "Certified", variant: "success" },
  muslim_friendly: { text: "Muslim Friendly", variant: "info" },
  unverified: { text: "Unverified", variant: "warning" },
};

function DiningRow({ option }: { option: PlanOption }) {
  const evidence = (option.raw?.halal_evidence ?? {}) as {
    claimed?: string | null;
    resolved?: string | null;
    cert_body?: string | null;
    notes?: string;
  };
  const label = HALAL_LABEL[option.halal_confidence ?? "unverified"];
  const downgraded =
    Boolean(evidence.claimed) && evidence.claimed !== evidence.resolved;

  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-[var(--border)]/50 last:border-0">
      <Badge variant={label.variant}>{label.text}</Badge>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium flex items-center gap-1">
          {option.title}
          {evidence.cert_body && (
            <span className="inline-flex items-center gap-0.5 text-[0.6rem] text-[var(--success)]">
              <BadgeCheck className="h-3 w-3" />
              {evidence.cert_body}
            </span>
          )}
        </p>
        {option.reasoning && (
          <p className="text-[0.65rem] text-[var(--muted)] italic">{option.reasoning}</p>
        )}
        {downgraded && (
          <p className="text-[0.6rem] text-[var(--warning)] mt-0.5">
            Claimed “{evidence.claimed}” — downgraded: {evidence.notes || "no certification source"}
          </p>
        )}
      </div>
      <OptionFeedback option={option} />
    </div>
  );
}

function AttractionRow({ option }: { option: PlanOption }) {
  return (
    <div className="py-1.5 border-b border-[var(--border)]/50 last:border-0">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium min-w-0 truncate">{option.title}</p>
        <div className="flex items-center gap-2 shrink-0">
          {option.price_amount != null && (
            <span className="text-xs text-[var(--brand-500)] font-semibold">
              {option.price_currency ?? "MYR"}{" "}
              {Number(option.price_amount).toLocaleString()}
            </span>
          )}
          <OptionFeedback option={option} />
        </div>
      </div>
      {option.reasoning && (
        <p className="text-[0.65rem] text-[var(--muted)] italic mt-0.5">
          &ldquo;{option.reasoning}&rdquo;
        </p>
      )}
    </div>
  );
}

/** Per-option thumbs. Each vote trains the brain's preference classifier. */
function OptionFeedback({ option }: { option: PlanOption }) {
  const [voted, setVoted] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);

  const vote = async (accepted: boolean) => {
    if (pending || voted !== null) return;
    setPending(true);
    const ok = await recordOptionOutcome(option, accepted);
    setPending(false);
    if (ok) setVoted(accepted);
  };

  if (voted !== null) {
    return (
      <span
        className={`text-[0.6rem] font-medium shrink-0 ${
          voted ? "text-[var(--success)]" : "text-[var(--muted)]"
        }`}
      >
        {voted ? "Saved ✓" : "Noted"}
      </span>
    );
  }

  return (
    <span className="flex items-center gap-1 shrink-0">
      <button
        type="button"
        aria-label={`Good pick: ${option.title}`}
        disabled={pending}
        onClick={() => void vote(true)}
        className="p-1 rounded-[var(--r-sm)] text-[var(--muted)] transition-colors hover:text-[var(--success)] hover:bg-[color-mix(in_srgb,var(--success)_12%,transparent)] disabled:opacity-40"
      >
        <ThumbsUp className="h-3 w-3" />
      </button>
      <button
        type="button"
        aria-label={`Poor pick: ${option.title}`}
        disabled={pending}
        onClick={() => void vote(false)}
        className="p-1 rounded-[var(--r-sm)] text-[var(--muted)] transition-colors hover:text-[var(--danger)] hover:bg-[color-mix(in_srgb,var(--danger)_12%,transparent)] disabled:opacity-40"
      >
        <ThumbsDown className="h-3 w-3" />
      </button>
    </span>
  );
}

function ResearchFeedback({ destination }: { destination: string }) {
  const [voted, setVoted] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);

  const vote = async (accepted: boolean) => {
    if (pending) return;
    setPending(true);
    const ok = await recordOutcome("research", { summary: destination }, accepted);
    setPending(false);
    if (ok) setVoted(accepted);
  };

  return (
    <div className="surface-card p-4 text-center">
      {voted === null ? (
        <>
          <p className="text-xs text-[var(--muted)] mb-2">Was this research helpful?</p>
          <div className="flex justify-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              loading={pending}
              onClick={() => void vote(true)}
            >
              <ThumbsUp className="h-3.5 w-3.5" /> Yes
            </Button>
            <Button
              variant="ghost"
              size="sm"
              loading={pending}
              onClick={() => void vote(false)}
            >
              <ThumbsDown className="h-3.5 w-3.5" /> No
            </Button>
          </div>
        </>
      ) : (
        <p className="text-xs text-[var(--success)]">
          Thanks — written to the brain. Your next plan starts from this.
        </p>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Itinerary timeline
// --------------------------------------------------------------------------- //

function ItineraryTimeline({ items }: { items: ItineraryItem[] }) {
  // Group by day
  const days = new Map<number, ItineraryItem[]>();
  for (const item of items) {
    const list = days.get(item.day_index) ?? [];
    list.push(item);
    days.set(item.day_index, list);
  }

  return (
    <div className="space-y-6">
      {Array.from(days.entries()).map(([dayIndex, dayItems]) => (
        <section key={dayIndex}>
          <h4 className="text-sm font-semibold mb-2 text-[var(--brand-500)]">
            Day {dayIndex}
          </h4>
          <ol className="space-y-2 border-l-2 border-[var(--border)] pl-4 ml-2">
            {dayItems.map((item, idx) => (
              <li key={idx} className="relative">
                <span className="absolute -left-[1.35rem] top-1.5 h-2.5 w-2.5 rounded-full bg-[var(--brand-400)]" />
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
                {item.reasoning && (
                  <p className="mt-0.5 text-xs text-[var(--muted)] italic">{item.reasoning}</p>
                )}
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
