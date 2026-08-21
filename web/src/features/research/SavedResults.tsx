import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button, Badge, EmptyState, Skeleton } from "@/components/ui";
import { Save, Plane, Trash2, RotateCcw } from "@/components/ui/icons";
import { api } from "@/lib/api";
import { usePlanStore, type PlanResults } from "@/stores/planStore";

/**
 * Research → Saved results. The traveller keeps any result (flights / places /
 * full trip) here from the results page, and re-opens it — loading the snapshot
 * back into the Command Center so they can pick up where they left off.
 */
type Saved = { id: string; scope: string; title: string; destination: string | null; created_at: string | null };

export function SavedResults() {
  const [items, setItems] = useState<Saved[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = () =>
    api.get<{ saved: Saved[] }>("/saved?kind=result").then((d) => setItems(d.saved)).catch(() => setItems([]));
  useEffect(() => { void load(); }, []);

  const reopen = async (id: string) => {
    setBusy(id);
    try {
      const r = await api.get<{ scope: string; results: PlanResults }>(`/saved/${id}`);
      usePlanStore.getState().setResults(r.results, r.scope);
      toast.success("Loaded — pick up where you left off.");
      navigate("/");
    } catch {
      toast.error("Couldn't re-open that result.");
    } finally {
      setBusy(null);
    }
  };

  const del = async (id: string) => {
    try {
      await api.del(`/saved/${id}`);
      setItems((x) => (x ?? []).filter((s) => s.id !== id));
    } catch {
      toast.error("Delete failed.");
    }
  };

  if (items === null) {
    return (
      <div className="grid gap-3 py-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-28 w-full" />)}
      </div>
    );
  }
  if (!items.length) {
    return (
      <div className="py-10">
        <EmptyState
          icon={<Save className="h-10 w-10" />}
          title="No saved results yet"
          description="On any results page, tap “Save result” — it lands here so you can re-open and re-run it anytime."
        />
      </div>
    );
  }
  return (
    <div className="grid gap-3 py-3 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((s) => (
        <div key={s.id} className="surface-card group relative p-4">
          <div className="flex items-start gap-2">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-500)]">
              <Plane className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{s.title}</p>
              <div className="mt-1"><Badge variant="brand">{s.scope.replace(/_/g, " ")}</Badge></div>
            </div>
            <button
              aria-label="Delete saved result"
              onClick={() => void del(s.id)}
              className="text-[var(--muted)] opacity-0 transition-opacity hover:text-[var(--danger)] group-hover:opacity-100"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-3">
            <Button size="sm" onClick={() => void reopen(s.id)} loading={busy === s.id}>
              <RotateCcw className="h-3.5 w-3.5" /> Re-open
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
