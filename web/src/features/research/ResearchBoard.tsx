import { Compass, Globe, ShieldAlert, Newspaper, ThumbsUp, ThumbsDown } from "lucide-react";
import { Button, EmptyState, OptionCard, Tabs, TabsList, TabsTrigger, TabsContent, Badge } from "@/components/ui";
import { usePlanStore } from "@/stores/planStore";
import type { ItineraryItem } from "@/stores/planStore";

/**
 * Research Board (spec §3.2). Tabbed destination intelligence — Flights, Hotels,
 * Itinerary, and Intelligence. Each pick shows reasoning ("Why this?").
 */
export function ResearchBoard() {
  const results = usePlanStore((s) => s.results);

  const flights = results?.flight?.options ?? [];
  const hotels = results?.hotel?.options ?? [];
  const itinerary = results?.itinerary?.items ?? [];
  const weatherSummary = results?.weather_risk?.summary;
  const researchSummary = results?.research?.summary;

  if (!results) {
    return (
      <div className="mx-auto w-full max-w-6xl">
        <header className="pt-2 pb-6">
          <h2 className="font-[family-name:var(--font-display)] text-2xl tracking-tight">
            Research Board
          </h2>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Destination intelligence — not a chat blob. Each pick shows the reasoning.
          </p>
        </header>
        <div className="mt-12">
          <EmptyState
            icon={<Compass className="h-10 w-10" />}
            title="No research runs yet"
            description="Kick off a trip from the Command Center — agents will publish their findings here."
            action={<Button variant="secondary">Open Command Center</Button>}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl">
      <header className="pt-2 pb-6">
        <h2 className="font-[family-name:var(--font-display)] text-2xl tracking-tight">
          Research Board
        </h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Destination intelligence — not a chat blob. Each pick shows the reasoning.
        </p>
      </header>

      <Tabs defaultValue="flights">
        <TabsList>
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
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {flights.map((opt) => (
                <OptionCard key={opt.id} option={opt} />
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="hotels">
          {hotels.length === 0 ? (
            <p className="text-sm text-[var(--muted)] py-6">No hotel options yet.</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {hotels.map((opt) => (
                <OptionCard key={opt.id} option={opt} />
              ))}
            </div>
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

            {/* Dining — Halal verification */}
            {results?.research?.options?.filter(o => o.kind === "restaurant").length > 0 && (
              <div className="surface-card p-4">
                <h4 className="text-sm font-semibold mb-3">Dining — Halal Verification</h4>
                <div className="space-y-2">
                  {results.research.options.filter(o => o.kind === "restaurant").map((opt) => (
                    <div key={opt.id} className="flex items-start gap-2 py-1.5 border-b border-[var(--border)]/50 last:border-0">
                      <Badge variant={
                        opt.halal_confidence === "certified" ? "success" :
                        opt.halal_confidence === "muslim_friendly" ? "info" : "warning"
                      }>
                        {opt.halal_confidence === "certified" ? "Certified" :
                         opt.halal_confidence === "muslim_friendly" ? "Muslim Friendly" : "Unverified"}
                      </Badge>
                      <div className="min-w-0">
                        <p className="text-xs font-medium">{opt.title}</p>
                        {opt.reasoning && <p className="text-[0.65rem] text-[var(--muted)] italic">{opt.reasoning}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Attractions with reasoning */}
            {results?.research?.options?.filter(o => o.kind === "activity").length > 0 && (
              <div className="surface-card p-4">
                <h4 className="text-sm font-semibold mb-3">Attractions — Why Journava Chose These</h4>
                <div className="space-y-2">
                  {results.research.options.filter(o => o.kind === "activity").map((opt) => (
                    <div key={opt.id} className="py-1.5 border-b border-[var(--border)]/50 last:border-0">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium">{opt.title}</p>
                        {opt.price_amount != null && (
                          <span className="text-xs text-[var(--brand-500)] font-semibold shrink-0">
                            {opt.price_currency ?? "MYR"} {Number(opt.price_amount).toLocaleString()}
                          </span>
                        )}
                      </div>
                      {opt.reasoning && (
                        <p className="text-[0.65rem] text-[var(--muted)] italic mt-0.5">&ldquo;{opt.reasoning}&rdquo;</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Outcome feedback */}
            {(researchSummary || results?.research?.options?.length) && (
              <div className="surface-card p-4 text-center">
                <p className="text-xs text-[var(--muted)] mb-2">Was this research helpful?</p>
                <div className="flex justify-center gap-3">
                  <button className="flex items-center gap-1 text-xs text-[var(--success)] hover:underline">
                    <ThumbsUp className="h-3.5 w-3.5" /> Yes
                  </button>
                  <button className="flex items-center gap-1 text-xs text-[var(--muted)] hover:underline">
                    <ThumbsDown className="h-3.5 w-3.5" /> No
                  </button>
                </div>
              </div>
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
