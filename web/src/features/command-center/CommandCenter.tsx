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

export function CommandCenter() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { events } = useAgentStream();

  const [scopes, setScopes] = useState<Scope[] | null>(null);

  const results = usePlanStore((s) => s.results);
  const activeScope = usePlanStore((s) => s.activeScope);
  const inputs = usePlanStore((s) => s.inputs);
  const resetInputs = usePlanStore((s) => s.resetInputs);
  const jobRunning = usePlanStore((s) => s.jobRunning);
  const runPlanJob = usePlanStore((s) => s.runPlanJob);

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

  const runPlan = async () => {
    if (!scope) return;
    const payload: Record<string, unknown> = {
      goal: inputs.goal.trim(),
      scope: scope.slug,
      travellers: inputs.travellers,
      budget_currency: inputs.budget_currency,
    };
    // Only send what the traveller actually filled in — an empty string would
    // fail date validation, and a zero budget is not the same as "no budget".
    if (inputs.start_date) payload.start_date = inputs.start_date;
    if (inputs.end_date) payload.end_date = inputs.end_date;
    if (inputs.budget_amount) payload.budget_amount = Number(inputs.budget_amount);
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
      <LoadingOverlay
        open={jobRunning}
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
          onAskAgain={() => usePlanStore.setState({ results: null, activeScope: null })}
          onBack={backToPicker}
          onOpenTrip={() => navigate("/trip")}
        />
      )}
    </>
  );
}
