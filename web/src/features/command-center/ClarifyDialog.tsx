import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "framer-motion";
import { ArrowRight, Plane, Sparkles, X } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { cn } from "@/lib/cn";

/**
 * Just-in-time clarification popup. The "Plan everything" button is always
 * clickable; when the prompt is missing a departure airport or names a country
 * without a city, the agent pops these one or two questions, then continues.
 */
export interface ClarifyState {
  needs_origin: boolean;
  country_only: { country: string; cities: string[]; recommended?: string } | null;
  date_suggestions?: { label: string; start_date: string; end_date: string }[];
}

export function ClarifyDialog({
  state,
  onCancel,
  onSubmit,
}: {
  state: ClarifyState;
  onCancel: () => void;
  onSubmit: (answers: { origin?: string; city?: string; country?: string; start_date?: string; end_date?: string }) => void;
}) {
  const [origin, setOrigin] = useState("");
  // "" = let the agent suggest (the default); a chip or the text box sets it.
  const [city, setCity] = useState("");
  const [dateIdx, setDateIdx] = useState<number | null>(null);
  const country = state.country_only?.country;
  const recommended = state.country_only?.recommended || state.country_only?.cities?.[0];
  const dates = state.date_suggestions ?? [];
  const ready = !state.needs_origin || origin.trim().length > 0;

  const submit = () => {
    const picked = dateIdx != null ? dates[dateIdx] : undefined;
    onSubmit({
      origin: origin.trim() || undefined,
      // "You suggest" (blank) resolves to the agent's recommended city, so the
      // plan runs for a real city (and flights get a real airport) — never a
      // bare country.
      city: city.trim() || (state.country_only ? recommended : undefined),
      country: state.country_only ? country : undefined,
      start_date: picked?.start_date,
      end_date: picked?.end_date,
    });
  };

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onCancel()}>
      <Dialog.Portal>
        <Dialog.Overlay asChild>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[85] bg-black/50 backdrop-blur-sm"
          />
        </Dialog.Overlay>
        <Dialog.Content asChild>
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            className={cn(
              "fixed left-1/2 top-1/2 z-[86] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2",
              "rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--elevated)] p-6 shadow-[var(--shadow-2)]",
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <Dialog.Title className="flex items-center gap-2 font-[family-name:var(--font-display)] text-lg">
                  <Plane className="h-5 w-5 text-[var(--brand-500)]" />
                  Just a couple of things
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm text-[var(--muted)]">
                  A quick check so your agents plan the right flights.
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <Button variant="ghost" size="icon" aria-label="Close">
                  <X className="h-4 w-4" />
                </Button>
              </Dialog.Close>
            </div>

            <div className="mt-5 space-y-5">
              {state.needs_origin && (
                <div>
                  <label className="mb-1.5 block text-sm font-medium">Where are you flying from?</label>
                  <input
                    autoFocus
                    className="input-field"
                    placeholder="e.g. KLIA, Kuala Lumpur"
                    value={origin}
                    onChange={(event) => setOrigin(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && ready) submit();
                    }}
                    aria-label="Flying from"
                  />
                </div>
              )}

              {state.country_only && (
                <div>
                  <label className="mb-1.5 block text-sm font-medium">
                    Where in {country}?
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {state.country_only.cities.map((option) => (
                      <button
                        key={option}
                        type="button"
                        onClick={() => setCity(option)}
                        className={cn(
                          "rounded-[var(--r-pill)] border px-3 py-1.5 text-xs font-medium transition-colors",
                          city === option
                            ? "border-[var(--brand-500)] bg-[color-mix(in_srgb,var(--brand-400)_18%,transparent)] text-[var(--brand-600)]"
                            : "border-[var(--border)] hover:border-[var(--brand-400)]",
                        )}
                      >
                        {option}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => setCity("")}
                      className={cn(
                        "inline-flex items-center gap-1 rounded-[var(--r-pill)] border px-3 py-1.5 text-xs font-medium transition-colors",
                        city === ""
                          ? "border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_18%,transparent)] text-[var(--accent)]"
                          : "border-[var(--border)] hover:border-[var(--accent)]",
                      )}
                    >
                      <Sparkles className="h-3.5 w-3.5" />
                      {recommended ? `Suggest (${recommended})` : "You suggest"}
                    </button>
                  </div>
                  <input
                    className="input-field mt-2"
                    placeholder="…or type a city / area"
                    value={state.country_only.cities.includes(city) ? "" : city}
                    onChange={(event) => setCity(event.target.value)}
                    aria-label="Custom city"
                  />
                  <p className="mt-1.5 text-[0.65rem] text-[var(--muted)]">
                    We'll plan {city.trim() || recommended} first — you can try other cities on the results.
                  </p>
                </div>
              )}

              {dates.length > 0 && (
                <div>
                  <label className="mb-1.5 block text-sm font-medium">When? (no dates given)</label>
                  <div className="flex flex-wrap gap-2">
                    {dates.map((d, i) => (
                      <button
                        key={i}
                        type="button"
                        onClick={() => setDateIdx(dateIdx === i ? null : i)}
                        className={cn(
                          "rounded-[var(--r-pill)] border px-3 py-1.5 text-xs font-medium transition-colors",
                          dateIdx === i
                            ? "border-[var(--brand-500)] bg-[color-mix(in_srgb,var(--brand-400)_18%,transparent)] text-[var(--brand-600)]"
                            : "border-[var(--border)] hover:border-[var(--brand-400)]",
                        )}
                      >
                        {d.label} · {d.start_date.slice(5)}→{d.end_date.slice(5)}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="mt-6 flex items-center justify-end gap-2">
              <Button variant="ghost" onClick={onCancel}>
                Cancel
              </Button>
              <Button disabled={!ready} onClick={submit}>
                Continue
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
