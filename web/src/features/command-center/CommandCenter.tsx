import { useState } from "react";
import { toast } from "sonner";
import { Mic, Paperclip, Image, Video, Sparkles, Plane, Building2, Calendar } from "lucide-react";
import { Button, LoadingOverlay, Select, OptionCard, Badge, confirm } from "@/components/ui";
import { useAsync } from "@/lib/useAsync";
import { api } from "@/lib/api";
import { usePlanStore } from "@/stores/planStore";
import type { AgentPlanResult } from "@/stores/planStore";
import { useAgentStream } from "@/hooks/useAgentStream";

const PACE_OPTIONS = [
  { value: "relaxed", label: "Relaxed — 1–2 things a day" },
  { value: "balanced", label: "Balanced" },
  { value: "packed", label: "Packed — see everything" },
];

/**
 * Command Center (spec §3.1) — one universal input, multimodal affordances,
 * quick actions. Phase 1 wires the full plan call and displays results.
 */
export function CommandCenter() {
  const [goal, setGoal] = useState("");
  const [pace, setPace] = useState("balanced");
  const { results, setResults, setLoading, setError } = usePlanStore();
  const { events } = useAgentStream();

  const handleCancel = async () => {
    const ok = await confirm({
      title: "Cancel planning?",
      body: "Agents are still working. This will stop further tiers from running.",
      confirmText: "Cancel plan",
    });
    if (!ok) return;
    try {
      await api.post("/cancel");
      toast.info("Plan cancelled.");
    } catch {
      // ignore
    }
  };

  const plan = useAsync(async () => {
    const ok = await confirm({
      title: "Start planning?",
      body: "Journava will wake the Chief Agent and its specialists to build your trip.",
      confirmText: "Plan it",
    });
    if (!ok) return;

    setLoading(true);
    try {
      const res = await api.post<{ results: Record<string, AgentPlanResult> }>("/plan", { goal, pace });
      setResults(res.results);
      toast.success("Plan complete — check the Research Board for details.");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Planning failed";
      setError(msg);
      toast.error(msg);
    }
  });

  return (
    <div className="mx-auto w-full max-w-3xl">
      <LoadingOverlay
        open={plan.loading}
        events={events}
        onCancel={handleCancel}
      />

      <header className="pt-6 pb-8 text-center">
        <h2 className="font-[family-name:var(--font-display)] text-3xl md:text-4xl tracking-tight">
          Where to next?
        </h2>
        <p className="mt-2 text-[var(--muted)]">
          Travel, run by agents. Describe the trip — they handle the rest.
        </p>
      </header>

      {/* Universal input */}
      <div className="surface-card p-4">
        <textarea
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          rows={3}
          placeholder="Plan a 7-day Venice trip for 2, budget RM8,000, we love food + culture, avoid crowds, max 1 connection."
          className="w-full resize-none bg-transparent text-[var(--text)] placeholder:text-[var(--muted)] outline-none"
        />
        <div className="mt-3 flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-1">
            {[Mic, Paperclip, Image, Video].map((Icon, index) => (
              <Button
                key={index}
                variant="ghost"
                size="icon"
                aria-label="Add input"
                onClick={() => toast.info("Multimodal capture arrives in Phase 2.")}
              >
                <Icon className="h-[18px] w-[18px]" />
              </Button>
            ))}
          </div>
          <Button
            loading={plan.loading}
            disabled={goal.trim().length === 0}
            onClick={() => void plan.run()}
          >
            <Sparkles className="h-4 w-4" />
            Plan my trip
          </Button>
        </div>
      </div>

      {/* Preference peek — full profile lives in §3.5 */}
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="mb-2 block text-sm font-medium">Trip pace</span>
          <Select
            value={pace}
            onValueChange={setPace}
            options={PACE_OPTIONS}
            aria-label="Trip pace"
          />
        </label>
      </div>

      {/* Quick actions */}
      <div className="mt-8 flex flex-wrap gap-2">
        {["Flights", "Hotels", "Explore", "Budget", "Trips"].map((action) => (
          <Button key={action} variant="secondary" size="sm">
            {action}
          </Button>
        ))}
      </div>

      {/* --- Plan Results --- */}
      {results && <PlanResults results={results} />}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Plan Results sub-component
// --------------------------------------------------------------------------- //

function PlanResults({ results }: { results: Record<string, AgentPlanResult> }) {
  const flights = results.flight?.options ?? [];
  const hotels = results.hotel?.options ?? [];
  const itinerary = results.itinerary?.items ?? [];
  const chiefSummary = results.chief?.summary;

  return (
    <div className="mt-10 space-y-8">
      {chiefSummary && (
        <div className="surface-card p-4 border-l-4 border-[var(--brand-500)]">
          <p className="text-sm font-medium">{chiefSummary}</p>
        </div>
      )}

      {/* Flights */}
      {flights.length > 0 && (
        <section>
          <h3 className="flex items-center gap-2 text-lg font-semibold mb-3">
            <Plane className="h-5 w-5 text-[var(--brand-500)]" />
            Flights
            <Badge variant="brand">{flights.length}</Badge>
          </h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {flights.map((opt) => (
              <OptionCard key={opt.id} option={opt} />
            ))}
          </div>
        </section>
      )}

      {/* Hotels */}
      {hotels.length > 0 && (
        <section>
          <h3 className="flex items-center gap-2 text-lg font-semibold mb-3">
            <Building2 className="h-5 w-5 text-[var(--brand-500)]" />
            Hotels
            <Badge variant="brand">{hotels.length}</Badge>
          </h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {hotels.map((opt) => (
              <OptionCard key={opt.id} option={opt} />
            ))}
          </div>
        </section>
      )}

      {/* Itinerary */}
      {itinerary.length > 0 && (
        <section>
          <h3 className="flex items-center gap-2 text-lg font-semibold mb-3">
            <Calendar className="h-5 w-5 text-[var(--brand-500)]" />
            Itinerary
            <Badge variant="brand">{itinerary.length} items</Badge>
          </h3>
          <ol className="space-y-2">
            {itinerary.map((item, idx) => (
              <li key={idx} className="surface-card p-3 flex items-start gap-3">
                <span className="shrink-0 h-7 w-7 rounded-full bg-[var(--brand-500)] text-white text-xs font-bold grid place-items-center">
                  {item.day_index}
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium">{item.title}</p>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-[var(--muted)]">
                    <Badge>{item.kind}</Badge>
                    {item.starts_at && <span>{item.starts_at}{item.ends_at ? ` – ${item.ends_at}` : ""}</span>}
                    {item.cost_amount != null && (
                      <span className="font-medium text-[var(--brand-500)]">
                        {item.cost_currency ?? "MYR"} {Number(item.cost_amount).toLocaleString()}
                      </span>
                    )}
                  </div>
                  {item.reasoning && (
                    <p className="mt-1 text-xs text-[var(--muted)] italic">{item.reasoning}</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
