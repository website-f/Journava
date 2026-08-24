import { useEffect, useState, type ReactNode } from "react";
import { Plane, ShieldCheck, Leaf, FileCheck2 } from "@/components/ui/icons";
import { Money } from "@/components/ui/Money";
import { api } from "@/lib/api";

/**
 * Agency console — the B2B surface. Shows the org's managed trips and the OTA
 * commission avoided by booking direct through Journava's agents ("bypass the
 * OTAs"), plus the corporate control tower: the active travel policy + how
 * compliant bookings are, where travellers are and how risky (duty of care),
 * and aggregate carbon (ESG). A hotel/DMC on the Partner portal, or a TMC
 * managing clients, uses the same agent mesh instead of paying an OTA its cut.
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

type Policy = {
  configured: boolean;
  max_fare_amount: number | null;
  fare_currency: string;
  max_cabin: string | null;
  preferred_carriers: string[];
  max_hotel_per_night: number | null;
  hotel_currency: string;
  preferred_hotels: string[];
  approval_threshold: number | null;
  notes: string;
};

type Traveller = {
  trip_id: string;
  destination: string;
  safety_level: string;
  advisory: string;
  embassy_phone: string | null;
};

type Corporate = {
  policy: Policy;
  policy_violations: number;
  duty_of_care: { travellers: Traveller[]; risk_counts: Record<string, number>; at_risk: number };
  esg: { total_co2_kg: number; total_offset_usd: number; trips_measured: number };
};

export function AgencyConsole() {
  const [data, setData] = useState<Overview | null>(null);
  const [corp, setCorp] = useState<Corporate | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get<Overview>("/agency/overview").catch(() => null),
      api.get<Corporate>("/agency/corporate").catch(() => null),
    ])
      .then(([o, c]) => {
        if (cancelled) return;
        if (o) setData(o);
        if (c) setCorp(c);
      })
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

      <div className="surface-card p-5">
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

      {/* Corporate control tower */}
      <PolicyCard corp={corp} />
      <DutyOfCareCard corp={corp} />
      <EsgCard corp={corp} />

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

function PolicyCard({ corp }: { corp: Corporate | null }) {
  const p = corp?.policy;
  const configured = p?.configured;
  return (
    <section className="surface-card p-4">
      <div className="mb-2 flex items-center gap-2">
        <FileCheck2 className="h-4 w-4 text-[var(--brand-500)]" />
        <h3 className="text-sm font-semibold">Corporate travel policy</h3>
        {configured && corp && (
          <span
            className={`ml-auto rounded-[var(--r-pill)] px-2 py-0.5 text-xs font-medium ${
              corp.policy_violations > 0
                ? "bg-[color-mix(in_srgb,var(--warning)_18%,transparent)] text-[var(--warning)]"
                : "bg-[color-mix(in_srgb,var(--success)_18%,transparent)] text-[var(--success)]"
            }`}
          >
            {corp.policy_violations > 0 ? `${corp.policy_violations} flagged` : "compliant"}
          </span>
        )}
      </div>
      {!configured ? (
        <p className="text-sm text-[var(--muted)]">
          No policy set. Upload your company travel policy in the assistant chat (📎) and Journava
          extracts the rules — the flight & hotel agents then flag anything out of policy.
        </p>
      ) : (
        <div className="flex flex-wrap gap-2 text-xs">
          {p!.max_fare_amount != null && (
            <Chip>
              Fare cap {p!.fare_currency} {p!.max_fare_amount.toLocaleString()}
            </Chip>
          )}
          {p!.max_cabin && <Chip>Max cabin: {p!.max_cabin.replace(/_/g, " ")}</Chip>}
          {p!.max_hotel_per_night != null && (
            <Chip>
              Hotel ≤ {p!.hotel_currency} {p!.max_hotel_per_night.toLocaleString()}/night
            </Chip>
          )}
          {p!.approval_threshold != null && (
            <Chip>
              Approval &gt; {p!.fare_currency} {p!.approval_threshold.toLocaleString()}
            </Chip>
          )}
          {p!.preferred_carriers.slice(0, 4).map((c) => (
            <Chip key={c}>✈ {c}</Chip>
          ))}
          {p!.preferred_hotels.slice(0, 3).map((h) => (
            <Chip key={h}>🏨 {h}</Chip>
          ))}
        </div>
      )}
    </section>
  );
}

function DutyOfCareCard({ corp }: { corp: Corporate | null }) {
  const doc = corp?.duty_of_care;
  return (
    <section className="surface-card p-4">
      <div className="mb-2 flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-[var(--brand-500)]" />
        <h3 className="text-sm font-semibold">Duty of care</h3>
        {doc && (
          <span className="ml-auto text-xs text-[var(--muted)]">
            {doc.at_risk > 0 ? `${doc.at_risk} traveller(s) need attention` : "all clear"}
          </span>
        )}
      </div>
      {!doc?.travellers.length ? (
        <p className="text-sm text-[var(--muted)]">
          Risk & emergency data appears here once trips include the safety agents.
        </p>
      ) : (
        <div className="space-y-2">
          {doc.travellers.slice(0, 8).map((t) => (
            <div key={t.trip_id} className="flex items-center gap-2">
              <RiskPill level={t.safety_level} />
              <span className="min-w-0 flex-1 truncate text-sm">{t.destination}</span>
              {t.embassy_phone && (
                <span className="shrink-0 text-[0.65rem] text-[var(--muted)]">☎ {t.embassy_phone}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function EsgCard({ corp }: { corp: Corporate | null }) {
  const esg = corp?.esg;
  return (
    <section className="surface-card p-4">
      <div className="mb-2 flex items-center gap-2">
        <Leaf className="h-4 w-4 text-[var(--success)]" />
        <h3 className="text-sm font-semibold">ESG · carbon</h3>
      </div>
      {!esg?.trips_measured ? (
        <p className="text-sm text-[var(--muted)]">
          Aggregate flight CO₂ appears here once trips run the sustainability agent.
        </p>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          <Tile label="Flight CO₂" value={`${esg.total_co2_kg.toLocaleString()} kg`} />
          <Tile label="Offset cost" value={<Money amount={esg.total_offset_usd} currency="USD" />} />
          <Tile label="Trips measured" value={String(esg.trips_measured)} />
        </div>
      )}
    </section>
  );
}

function RiskPill({ level }: { level: string }) {
  const map: Record<string, string> = {
    safe: "bg-[color-mix(in_srgb,var(--success)_18%,transparent)] text-[var(--success)]",
    caution: "bg-[color-mix(in_srgb,var(--warning)_18%,transparent)] text-[var(--warning)]",
    dangerous: "bg-[color-mix(in_srgb,var(--danger,#dc2626)_18%,transparent)] text-[var(--danger,#dc2626)]",
  };
  const cls = map[level] ?? "bg-[var(--bg)] text-[var(--muted)]";
  return (
    <span className={`shrink-0 rounded-[var(--r-pill)] px-2 py-0.5 text-[0.65rem] font-medium capitalize ${cls}`}>
      {level}
    </span>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-[var(--r-pill)] border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1">
      {children}
    </span>
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
