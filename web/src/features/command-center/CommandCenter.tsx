import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { LoadingOverlay, Skeleton, confirm } from "@/components/ui";
import { api } from "@/lib/api";
import { useAgentStream } from "@/hooks/useAgentStream";
import { usePlanStore } from "@/stores/planStore";
import type { Scope } from "@/lib/types";
import { PersonalHome } from "@/features/home/PersonalHome";
import { ScopePicker } from "./ScopePicker";
import { ScopedConsole } from "./ScopedConsole";
import { ScopedResults } from "./ScopedResults";
import { ClarifyDialog, type ClarifyState } from "./ClarifyDialog";

/**
 * Command Center — the main surface (spec §3.1), in three states:
 *
 *   pick   →  choose what you want (all 10 presets)
 *   ask    →  a focused console for that scope
 *   answer →  only the panels that scope produced
 *
 * The scope lives in the URL (`?scope=flights_only`), so a mode is linkable and
 * a reload doesn't dump the traveller back at the picker.
 */

type Phase = "pick" | "ask" | "answer";

/** A pasted social link → we read the post and plan from it (see runPlan). */
const SOCIAL_URL_RE =
  /https?:\/\/\S*(tiktok\.com|instagram\.com|instagr\.am|youtube\.com|youtu\.be|twitter\.com|x\.com|facebook\.com|fb\.watch)\S*/i;

interface SocialSeed {
  goal?: string;
  destination?: string;
  origin_hint?: string | null;
  vibe?: string;
  source_kind?: string;
}

export function CommandCenter() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { events } = useAgentStream();

  const [scopes, setScopes] = useState<Scope[] | null>(null);
  const [clarify, setClarify] = useState<ClarifyState | null>(null);

  const results = usePlanStore((s) => s.results);
  const activeScope = usePlanStore((s) => s.activeScope);
  const inputs = usePlanStore((s) => s.inputs);
  const resetInputs = usePlanStore((s) => s.resetInputs);
  const setInputs = usePlanStore((s) => s.setInputs);
  const jobRunning = usePlanStore((s) => s.jobRunning);
  const streaming = usePlanStore((s) => s.streaming);
  const runPlanJob = usePlanStore((s) => s.runPlanJob);

  // Remember the departure airport once resolved (typed or picked in the popup),
  // so re-planning a nearby city from the results keeps flying from the same place.
  const [replanOrigin, setReplanOrigin] = useState("");

  const scopeSlug = searchParams.get("scope");
  const scope = scopes?.find((entry) => entry.slug === scopeSlug) ?? null;

  useEffect(() => {
    api
      .get<Scope[]>("/scopes")
      .then(setScopes)
      .catch(() => {
        setScopes([]);
        toast.error("Could not load the planning modes.");
      });
  }, []);

  // Show the answer only when it belongs to the scope currently selected.
  const showingAnswer = Boolean(scope && results && activeScope === scope.slug);
  const phase: Phase = !scope ? "pick" : showingAnswer ? "answer" : "ask";

  const pickScope = (next: Scope) => {
    resetInputs();
    setSearchParams({ scope: next.slug });
  };

  const backToPicker = () => {
    setSearchParams({});
  };

  // The CTA is always clickable. Before running, ask the backend whether the
  // prompt is missing an origin or names a country without a city — if so, pop the
  // clarification dialog; otherwise dispatch straight away.
  const runPlan = async () => {
    if (!scope) return;

    // A pasted social link (TikTok / IG / YouTube / X / FB): read the post and
    // plan straight from what the creator showed — no need to retype anything.
    if (SOCIAL_URL_RE.test(inputs.goal)) {
      await planFromLink();
      return;
    }

    try {
      const check = await api.post<{ needs_clarification: boolean } & ClarifyState>(
        "/plan/clarify",
        { goal: inputs.goal.trim(), scope: scope.slug },
      );
      if (check.needs_clarification) {
        setClarify({
          needs_origin: check.needs_origin,
          country_only: check.country_only,
          date_suggestions: check.date_suggestions,
        });
        return;
      }
    } catch {
      // Clarification is a nicety — if the check fails, just run the plan.
    }
    await dispatchPlan();
  };

  // Read a pasted social link into a trip seed, then plan from the seed's goal
  // (not the raw URL) so results land in the normal results view.
  const planFromLink = async () => {
    if (!scope) return;
    const toastId = toast.loading("Reading your link…");
    let seed: SocialSeed | null = null;
    try {
      const res = await api.post<{ seed: SocialSeed | null; error?: string }>("/plan/social-seed", {
        goal: inputs.goal.trim(),
      });
      seed = res.seed;
      if (!seed || res.error) {
        toast.error(res.error || "Couldn't read that link — paste the caption instead.", { id: toastId });
        return;
      }
    } catch {
      toast.error("Couldn't reach the link reader — try again.", { id: toastId });
      return;
    }

    toast.success(
      `Read your ${seed.source_kind ?? "post"} — planning ${seed.destination || "your trip"}${seed.vibe ? ` · ${seed.vibe}` : ""}`,
      { id: toastId },
    );

    const payload: Record<string, unknown> = {
      goal: seed.goal || `Plan a trip to ${seed.destination}`,
      scope: scope.slug,
      travellers: inputs.travellers,
      budget_currency: inputs.budget_currency,
    };
    if (seed.destination) payload.destination = seed.destination;
    if (seed.origin_hint) payload.origin = seed.origin_hint;
    if (inputs.budget_amount != null) payload.budget_amount = inputs.budget_amount;
    if (scope.inputs.includes("pace")) payload.pace = inputs.pace;

    await runPlanJob(payload);

    const { error: runError, lastDurationMs } = usePlanStore.getState();
    if (runError) toast.error(runError);
    else if (lastDurationMs != null) toast.success(`${scope.label} done in ${(lastDurationMs / 1000).toFixed(1)}s`);
  };

  const dispatchPlan = async (extra?: {
    origin?: string; city?: string; country?: string; start_date?: string; end_date?: string;
  }) => {
    if (!scope) return;
    setClarify(null);

    // Fold the popup answers into the goal so the parser resolves a real airport.
    const clause: string[] = [];
    if (extra?.origin?.trim()) clause.push(`flying from ${extra.origin.trim()}`);
    const cityDest = extra?.city?.trim()
      ? `${extra.city.trim()}${extra.country ? `, ${extra.country}` : ""}`
      : "";
    if (cityDest) clause.push(`to ${cityDest}`);
    const goal = clause.length
      ? [inputs.goal.trim(), clause.join(" ")].filter(Boolean).join(" — ")
      : inputs.goal.trim();

    const payload: Record<string, unknown> = {
      goal,
      scope: scope.slug,
      travellers: inputs.travellers,
      budget_currency: inputs.budget_currency,
    };
    // Set the destination EXPLICITLY to the chosen city — the Chief honours an
    // explicit destination over goal-parsing, so "4 days in Japan" no longer
    // searches flights to a whole country (KUL→Japan); it flies KUL→Osaka.
    if (cityDest) payload.destination = cityDest;
    // Dates: a clarify suggestion wins over the (empty) form field.
    const startDate = extra?.start_date || inputs.start_date;
    const endDate = extra?.end_date || inputs.end_date;
    if (startDate) payload.start_date = startDate;
    if (endDate) payload.end_date = endDate;
    // Persist the resolved origin + dates so a later "re-plan a nearby city"
    // reuses them instead of dropping back to a bare goal.
    if (extra?.origin?.trim()) setReplanOrigin(extra.origin.trim());
    if (extra?.start_date || extra?.end_date) {
      setInputs({ start_date: startDate, end_date: endDate });
    }
    if (inputs.budget_amount != null) payload.budget_amount = inputs.budget_amount;
    if (scope.inputs.includes("pace")) payload.pace = inputs.pace;

    // Dispatch a background job (agents run off-request) and poll it in the
    // store, so navigating to the Agents Workspace doesn't cancel the run.
    await runPlanJob(payload);

    const { error: runError, lastDurationMs } = usePlanStore.getState();
    if (runError) {
      toast.error(runError);
    } else if (lastDurationMs != null) {
      toast.success(`${scope.label} done in ${(lastDurationMs / 1000).toFixed(1)}s`);
    }
  };

  const cancel = async () => {
    const ok = await confirm({
      title: "Cancel this run?",
      body: "Agents already working will finish, but nothing further will start.",
      confirmText: "Cancel run",
    });
    if (!ok) return;
    try {
      await api.post("/cancel");
      toast.info("Cancellation requested.");
    } catch {
      // The run may already have finished; nothing useful to say here.
    }
  };

  if (scopes === null) {
    return (
      <div className="mx-auto w-full max-w-5xl space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-32 w-full" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-32 w-full" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Block only until the first tier of results lands; after that the
          results render live behind a slim "still working" banner. */}
      <LoadingOverlay
        open={jobRunning && !results}
        events={events}
        onCancel={cancel}
        onWatch={() => navigate("/agents")}
      />

      {phase === "pick" && (
        <div className="space-y-9">
          <PersonalHome
            onLaunch={(slug, goal) => {
              resetInputs(goal ?? "");
              setSearchParams({ scope: slug });
            }}
          />
          <div className="mx-auto w-full max-w-5xl">
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
              Or choose a mode
            </h2>
            <ScopePicker scopes={scopes} onPick={pickScope} />
          </div>
        </div>
      )}

      {phase === "ask" && scope && (
        <ScopedConsole
          scope={scope}
          onBack={backToPicker}
          onRun={() => void runPlan()}
          running={jobRunning}
        />
      )}

      {phase === "answer" && scope && results && (
        <ScopedResults
          scope={scope}
          results={results}
          streaming={streaming}
          onAskAgain={() => usePlanStore.setState({ results: null, activeScope: null })}
          onBack={backToPicker}
          onOpenTrip={() => navigate("/trip")}
          onReplanCity={(city, country) =>
            void dispatchPlan({ city, country, origin: replanOrigin || undefined })
          }
        />
      )}

      {clarify && (
        <ClarifyDialog
          state={clarify}
          onCancel={() => setClarify(null)}
          onSubmit={(answers) => void dispatchPlan(answers)}
        />
      )}
    </>
  );
}
