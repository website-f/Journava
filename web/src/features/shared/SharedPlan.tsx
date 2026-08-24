import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Sparkles } from "@/components/ui/icons";
import { Button, Spinner } from "@/components/ui";
import { api, API_BASE } from "@/lib/api";
import { useAuth } from "@/providers/AuthProvider";
import { TripExtraPanels } from "@/features/command-center/ScopedResults";
import type { PlanResults } from "@/stores/planStore";

/**
 * Public, read-only view of a compiled plan — opened by a client with no account
 * from the Telegram link (`/s/:token`). Renders the same rich panels the consumer
 * sees, so the shared plan is interactive, not just a flat PDF.
 */
export function SharedPlan() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { status } = useAuth();
  const [state, setState] = useState<{ title: string; results: PlanResults } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const saveToMyTrips = async () => {
    if (status !== "authed") {
      toast.info("Sign in to Journava, then reopen this link to save the trip.");
      navigate("/");
      return;
    }
    setSaving(true);
    try {
      const res = await api.post<{ id?: string; error?: string }>("/saved/from-shared", { token });
      if (res.error) toast.error(res.error);
      else {
        toast.success("Saved to your trips!");
        navigate("/trip");
      }
    } catch {
      toast.error("Couldn't save this trip.");
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/shared/${token}`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        if (d.error || !d.results) setError(d.error || "This plan couldn't be loaded.");
        else setState({ title: d.title, results: d.results });
      })
      .catch(() => !cancelled && setError("This plan couldn't be loaded."));
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="min-h-[100dvh] bg-[var(--bg)] text-[var(--text)]">
      <header className="border-b border-[var(--border)] bg-[var(--surface)]">
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-4">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-[var(--brand-500)] text-white">
            <Sparkles className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">{state?.title ?? "Your trip"}</p>
            <p className="text-[0.7rem] text-[var(--muted)]">Prepared with Journava · interactive itinerary</p>
          </div>
          {state && (
            <Button size="sm" loading={saving} onClick={() => void saveToMyTrips()}>
              <Plus className="h-4 w-4" />
              Save to my trips
            </Button>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 py-6">
        {error ? (
          <div className="surface-card p-8 text-center text-sm text-[var(--muted)]">{error}</div>
        ) : !state ? (
          <div className="grid place-items-center py-24">
            <Spinner className="h-6 w-6 text-[var(--brand-500)]" />
          </div>
        ) : (
          <TripExtraPanels results={state.results} />
        )}
      </main>
    </div>
  );
}
