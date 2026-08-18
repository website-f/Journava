import { Compass } from "lucide-react";
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
            {weatherSummary && (
              <div className="surface-card p-4">
                <h4 className="text-sm font-semibold mb-1">Weather / Risk</h4>
                <p className="text-xs text-[var(--muted)]">{weatherSummary}</p>
              </div>
            )}
            {researchSummary && (
              <div className="surface-card p-4">
                <h4 className="text-sm font-semibold mb-1">Research</h4>
                <p className="text-xs text-[var(--muted)]">{researchSummary}</p>
              </div>
            )}
            {!weatherSummary && !researchSummary && (
              <p className="text-sm text-[var(--muted)]">
                Intelligence data (weather, YouTube, Reddit) arrives in Phase 2.
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
