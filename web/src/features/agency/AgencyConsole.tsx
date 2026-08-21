import { useEffect, useState, type ReactNode } from "react";
import { Plane } from "@/components/ui/icons";
import { Money } from "@/components/ui/Money";
import { api } from "@/lib/api";

/**
 * Agency console — the B2B surface. Shows the org's managed trips and the OTA
 * commission avoided by booking direct through Journava's agents ("bypass the
 * OTAs"). A hotel/DMC on the Partner portal, or a TMC managing clients, uses the
 * same agent mesh instead of paying Booking.com/Expedia their cut.
 */

type Trip = {
  id: string;
  goal?: string;
  scope?: string;
  destination?: string;
  option_count?: number;
  created_at?: string;
  saved: number;
};

type Overview = {
  metrics: { managed_trips: number; total_saved: number; currency: string; commission_rate_pct: number };
  trips: Trip[];
};

export function AgencyConsole() {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .get<Overview>("/agency/overview")
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const m = data?.metrics;
  const currency = m?.currency ?? "MYR";

  return (
    <div className="space-y-6">
      <header>
        <h2 className="font-[family-name:var(--font-display)] text-2xl tracking-tight">Agency Console</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Your agents search, book and monitor <strong>direct</strong> — bypassing the OTAs.
        </p>
      </header>

      <div className="surface-card border-l-4 border-[var(--success)] p-5">
        <p className="text-xs uppercase tracking-wide text-[var(--muted)]">OTA commission avoided</p>
        <p className="mt-1 text-3xl font-bold text-[var(--success)]">
          <Money amount={m?.total_saved ?? 0} currency={currency} />
        </p>
        <p className="mt-1 text-sm text-[var(--muted)]">
          across {m?.managed_trips ?? 0} managed trips — booked direct via Atlas/NDC, no ~
          {m?.commission_rate_pct ?? 10}% middleman cut.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Tile label="Managed trips" value={String(m?.managed_trips ?? 0)} />
        <Tile label="Commission saved" value={<Money amount={m?.total_saved ?? 0} currency={currency} />} />
        <Tile label="OTA cut avoided" value={`~${m?.commission_rate_pct ?? 10}%`} />
      </div>

      <section>
        <h3 className="mb-2 text-lg font-semibold">Managed trips</h3>
        {loading ? (
          <p className="text-sm text-[var(--muted)]">Loading…</p>
        ) : !data?.trips.length ? (
          <p className="text-sm text-[var(--muted)]">No trips yet — run a plan and it appears here.</p>
        ) : (
          <div className="space-y-2">
            {data.trips.map((t) => (
              <div key={t.id} className="surface-card flex items-center gap-3 p-3">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-500)]">
                  <Plane className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{t.destination || t.goal || "Trip"}</p>
                  <p className="truncate text-xs text-[var(--muted)]">
                    {(t.scope ?? "").replace(/_/g, " ")} · {t.option_count ?? 0} options
                  </p>
                </div>
                {t.saved > 0 && (
                  <span className="shrink-0 text-xs font-semibold text-[var(--success)]">
                    +<Money amount={t.saved} currency={currency} />
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="surface-card p-3 text-center">
      <p className="text-lg font-semibold text-[var(--brand-500)]">{value}</p>
      <p className="mt-0.5 text-xs text-[var(--muted)]">{label}</p>
    </div>
  );
}
