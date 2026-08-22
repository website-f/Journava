import { ArrowLeft, Mic, Paperclip, Image as ImageIcon, Sparkles, Video } from "@/components/ui/icons";
import { toast } from "sonner";
import { Badge, Button, DateRangePicker, NumberField, Select } from "@/components/ui";
import { cn } from "@/lib/cn";
import { usePlanStore, type PlanInputs } from "@/stores/planStore";
import type { Scope } from "@/lib/types";

/**
 * The scoped Command Center: one focused question, with only the inputs that
 * scope actually uses.
 *
 * A flights search asks for dates, travellers and a budget. A food search asks
 * for a budget and nothing else. Showing every field for every scope is how a
 * form starts feeling like paperwork, so `scope.inputs` decides what appears.
 */

const PACE_OPTIONS = [
  { value: "relaxed", label: "Relaxed — 1–2 things a day" },
  { value: "balanced", label: "Balanced" },
  { value: "packed", label: "Packed — see everything" },
];

const CURRENCIES = [
  { value: "MYR", label: "MYR — Ringgit" },
  { value: "SGD", label: "SGD — Singapore Dollar" },
  { value: "USD", label: "USD — US Dollar" },
  { value: "EUR", label: "EUR — Euro" },
  { value: "GBP", label: "GBP — Pound" },
  { value: "AED", label: "AED — Dirham" },
  { value: "JPY", label: "JPY — Yen" },
];

export function ScopedConsole({
  scope,
  onBack,
  onRun,
  running,
}: {
  scope: Scope;
  onBack: () => void;
  onRun: () => void;
  running: boolean;
}) {
  const inputs = usePlanStore((s) => s.inputs);
  const setInputs = usePlanStore((s) => s.setInputs);

  const wants = (field: string) => scope.inputs.includes(field as never);
  // "route" is a marker the clarify step reads — it renders no field here; the CTA
  // is always clickable and the popup asks for origin/city only if the prompt lacks them.
  const canRun = inputs.goal.trim().length > 2 && !running;

  return (
    <div className="mx-auto w-full max-w-3xl">
      <div className="flex items-center gap-2 pt-2 pb-4">
        <Button variant="ghost" size="sm" onClick={onBack} disabled={running}>
          <ArrowLeft className="h-4 w-4" />
          All modes
        </Button>
        <div className="min-w-0 flex-1" />
        <Badge variant="brand">{scope.agent_count} agents</Badge>
        <Badge>~{scope.estimate_seconds}s</Badge>
      </div>

      <header className="pb-5">
        <h2 className="font-[family-name:var(--font-display)] text-2xl tracking-tight">
          {scope.label}
        </h2>
        <p className="mt-1 text-sm text-[var(--muted)]">{scope.description}</p>
      </header>

      {/* The ask */}
      <div className="surface-card p-4">
        <textarea
          value={inputs.goal}
          onChange={(event) => setInputs({ goal: event.target.value })}
          onKeyDown={(event) => {
            // Ctrl/Cmd+Enter runs, so a long prompt doesn't need a mouse trip.
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && canRun) {
              event.preventDefault();
              onRun();
            }
          }}
          rows={3}
          placeholder={scope.placeholder}
          className="w-full resize-none bg-transparent text-[var(--text)] outline-none placeholder:text-[var(--muted)]"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1">
            {[Mic, Paperclip, ImageIcon, Video].map((Icon, index) => (
              <Button
                key={index}
                variant="ghost"
                size="icon"
                aria-label="Add input"
                onClick={() => toast.info("Multimodal capture is not wired up yet.")}
              >
                <Icon className="h-[18px] w-[18px]" />
              </Button>
            ))}
          </div>
          <Button loading={running} disabled={!canRun} onClick={onRun}>
            <Sparkles className="h-4 w-4" />
            {scope.cta}
          </Button>
        </div>
      </div>

      {/* Only the fields this scope uses */}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {wants("dates") && (
          <Field label="Dates" hint="Pick a range — leave the return open for one-way" className="sm:col-span-2">
            <DateRangePicker
              value={{ start: inputs.start_date || undefined, end: inputs.end_date || undefined }}
              onChange={(r) => setInputs({ start_date: r.start ?? "", end_date: r.end ?? "" })}
              placeholder="When are you travelling?"
            />
          </Field>
        )}

        {wants("travellers") && (
          <Field label="Travellers">
            <NumberField
              min={1}
              max={9}
              allowEmpty={false}
              value={inputs.travellers}
              onValueChange={(n) => setInputs({ travellers: n ?? 1 })}
              aria-label="Number of travellers"
            />
          </Field>
        )}

        {wants("budget") && (
          <Field label="Budget" hint="A soft cap — it shapes ranking, never filters">
            <div className="flex gap-2">
              <div className="w-24 shrink-0">
                <Select
                  value={inputs.budget_currency}
                  onValueChange={(value) => setInputs({ budget_currency: value })}
                  options={CURRENCIES}
                  // Show just the code in the narrow trigger; the dropdown keeps
                  // the full "MYR — Ringgit" label.
                  renderValue={(v) => v ?? "MYR"}
                  aria-label="Budget currency"
                />
              </div>
              <NumberField
                min={0}
                placeholder="e.g. 8000"
                value={inputs.budget_amount}
                onValueChange={(n) => setInputs({ budget_amount: n })}
                aria-label="Budget amount"
              />
            </div>
          </Field>
        )}

        {wants("pace") && (
          <Field label="Pace">
            <Select
              value={inputs.pace}
              onValueChange={(value) => setInputs({ pace: value as PlanInputs["pace"] })}
              options={PACE_OPTIONS}
              aria-label="Trip pace"
            />
          </Field>
        )}
      </div>

      <p className="mt-4 text-[0.7rem] text-[var(--muted)]">
        Running: {scope.agents.join(" · ")}
      </p>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1.5 block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[0.65rem] text-[var(--muted)]">{hint}</span>}
    </label>
  );
}
