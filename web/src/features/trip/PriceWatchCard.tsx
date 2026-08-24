import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { TrendingUp, Trash2 } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { Money } from "@/components/ui/Money";
import { api } from "@/lib/api";
import { usePlanStore } from "@/stores/planStore";

/**
 * Price-drop autopilot — arm a watch on the trip's fare; Journava re-prices it
 * and, when it drops past the threshold, alerts (and, if armed, captures the
 * cheaper fare to rebook). "Check now" runs the sweep on demand; the simulate
 * toggle forces a synthetic drop so the autopilot is demoable instantly.
 */

type Watch = {
  id: string;
  origin: string;
  destination: string;
  depart_date: string | null;
  baseline_amount: number;
  currency: string;
  threshold_pct: number;
  auto_rebook: boolean;
  last_amount: number | null;
  status: "active" | "triggered" | "rebooked";
};

type RunResult = {
  checked: number;
  simulated: boolean;
  triggered: { route: string; was: number; now: number; drop_pct: number; currency: string; status: string }[];
};

const STATUS_STYLE: Record<string, string> = {
  active: "bg-[var(--bg)] text-[var(--muted)]",
  triggered: "bg-[color-mix(in_srgb,var(--warning)_16%,transparent)] text-[var(--warning)]",
  rebooked: "bg-[color-mix(in_srgb,var(--success)_16%,transparent)] text-[var(--success)]",
};

export function PriceWatchCard() {
  const results = usePlanStore((s) => s.results);
  const [watches, setWatches] = useState<Watch[]>([]);
  const [threshold, setThreshold] = useState(10);
  const [auto, setAuto] = useState(true);
  const [simulate, setSimulate] = useState(false);
  const [busy, setBusy] = useState(false);

  // Prefill from the trip's selected flight.
  const seed = useMemo(() => {
    const flight = results?.flight;
    const route = (flight?.data as { route?: { origin?: string; destination?: string; depart?: string } } | undefined)
      ?.route;
    const opts = flight?.options ?? [];
    const priced = opts
      .map((o) => (o.price_amount != null ? Number(o.price_amount) : null))
      .filter((n): n is number => n != null && n > 0);
    const baseline = priced.length ? Math.min(...priced) : null;
    const currency = opts.find((o) => o.price_currency)?.price_currency ?? "MYR";
    if (!route?.origin || !route?.destination || baseline == null) return null;
    return { origin: route.origin, destination: route.destination, depart: route.depart ?? null, baseline, currency };
  }, [results]);

  const load = async () => {
    try {
      const res = await api.get<{ watches: Watch[] }>("/watch/price");
      setWatches(res.watches ?? []);
    } catch {
      /* ignore */
    }
  };
  useEffect(() => {
    void load();
  }, []);

  const arm = async () => {
    if (!seed) return;
    setBusy(true);
    try {
      await api.post("/watch/price", {
        origin: seed.origin,
        destination: seed.destination,
        depart_date: seed.depart,
        baseline_amount: seed.baseline,
        currency: seed.currency,
        threshold_pct: threshold,
        auto_rebook: auto,
      });
      toast.success(`Watching ${seed.origin}→${seed.destination} — alert on a ${threshold}% drop.`);
      await load();
    } catch {
      toast.error("Couldn't arm the fare watch.");
    } finally {
      setBusy(false);
    }
  };

  const checkNow = async () => {
    setBusy(true);
    try {
      const res = await api.post<RunResult>("/watch/price/run", { simulate });
      if (res.triggered.length) {
        const t = res.triggered[0];
        toast.success(`Fare dropped ${t.drop_pct}% on ${t.route} — ${t.status === "rebooked" ? "auto-rebooked" : "alert sent"}.`);
      } else {
        toast.info(`Checked ${res.checked} watch(es) — no drop past threshold yet.`);
      }
      await load();
    } catch {
      toast.error("Couldn't run the price check.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await api.del(`/watch/price/${id}`);
      await load();
    } catch {
      toast.error("Couldn't remove the watch.");
    }
  };

  return (
    <section className="mt-8">
      <div className="surface-card p-5">
        <div className="mb-3 flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-[var(--brand-500)]" />
          <h3 className="text-base font-semibold">Price-drop autopilot</h3>
        </div>
        <p className="mb-4 text-sm text-[var(--muted)]">
          Journava re-prices your fare in the background and alerts you the moment it drops — and, if
          armed, captures the cheaper bookable fare so you can rebook in one tap.
        </p>

        {seed ? (
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm">
            <span className="font-medium">
              {seed.origin} → {seed.destination}
            </span>
            <span className="text-[var(--muted)]">
              from <Money amount={seed.baseline} currency={seed.currency} />
            </span>
            <label className="flex items-center gap-1.5 text-[var(--muted)]">
              Alert on
              <select
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))}
                className="rounded-[var(--r-sm)] border border-[var(--border)] bg-[var(--elevated)] px-1.5 py-0.5"
              >
                {[5, 10, 15, 20].map((v) => (
                  <option key={v} value={v}>
                    {v}%
                  </option>
                ))}
              </select>
              drop
            </label>
            <label className="flex items-center gap-1.5 text-[var(--muted)]">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
              Auto-rebook within budget
            </label>
            <Button onClick={arm} loading={busy} size="sm">
              Watch this fare
            </Button>
          </div>
        ) : (
          <p className="mb-4 text-sm text-[var(--muted)]">Open a trip with a flight to arm a fare watch.</p>
        )}

        {watches.length > 0 && (
          <ul className="mb-3 space-y-1.5">
            {watches.map((w) => (
              <li
                key={w.id}
                className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] px-3 py-2 text-sm"
              >
                <span className="font-medium">
                  {w.origin}→{w.destination}
                </span>
                <span className="text-[var(--muted)]">
                  baseline <Money amount={w.baseline_amount} currency={w.currency} />
                  {w.last_amount != null && (
                    <>
                      {" · now "}
                      <Money amount={w.last_amount} currency={w.currency} />
                    </>
                  )}
                </span>
                <span className={`ml-auto rounded-[var(--r-pill)] px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[w.status]}`}>
                  {w.status}
                </span>
                <button onClick={() => remove(w.id)} aria-label="Remove watch" className="text-[var(--muted)] hover:text-[var(--danger)]">
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" onClick={checkNow} loading={busy} size="sm">
            Check now
          </Button>
          <label className="flex items-center gap-1.5 text-xs text-[var(--muted)]">
            <input type="checkbox" checked={simulate} onChange={(e) => setSimulate(e.target.checked)} />
            Simulate a price drop (demo)
          </label>
        </div>
      </div>
    </section>
  );
}
