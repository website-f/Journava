import { useCallback, useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import {
  TrendingUp, Plane, ShieldCheck, CreditCard, Leaf, AlertTriangle, CheckCircle2, Zap, Sparkles, FileCheck2, Building2, Calendar, Download,
} from "@/components/ui/icons";
import { Button, Badge, Select } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import { Money } from "@/components/ui/Money";
import { API_BASE, api } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ shared */

function useGet<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    api.get<T>(path).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
  }, [path]);
  useEffect(() => { reload(); }, [reload]);
  return { data, loading, reload };
}

function PageHead({ title, subtitle, icon: Icon }: { title: string; subtitle: string; icon: typeof Plane }) {
  return (
    <header className="mb-6 flex items-start gap-3">
      <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-500)]">
        <Icon className="h-5 w-5" />
      </span>
      <div>
        <h1 className="font-[family-name:var(--font-display)] text-2xl tracking-tight">{title}</h1>
        <p className="mt-0.5 text-sm text-[var(--muted)]">{subtitle}</p>
      </div>
    </header>
  );
}

function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("surface-card p-5", className)}>{children}</div>;
}

function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "success" | "warning" | "brand" }) {
  const color = tone === "success" ? "text-[var(--success)]" : tone === "warning" ? "text-[var(--warning)]" : "text-[var(--brand-500)]";
  return (
    <div className="surface-card p-4">
      <p className={cn("text-2xl font-bold", color)}>{value}</p>
      <p className="mt-1 text-xs text-[var(--muted)]">{label}</p>
    </div>
  );
}

/* --------------------------------------------------------------- Overview */

type Overview = { metrics: { managed_trips: number; total_saved: number; currency: string } };
type Corporate = {
  policy: { configured: boolean };
  policy_violations: number;
  duty_of_care: { at_risk: number; travellers: unknown[] };
  esg: { total_co2_kg: number; trips_measured: number };
};
type Hold = { id: string; amount: number; currency: string; released: number; refunded: number; status: string; remaining?: number; booking_ref: string; description?: string };
type FirewallState = { listings: { healthy: boolean; discrepancies: unknown[] }[] };

export function ConsoleOverview() {
  const ov = useGet<Overview>("/agency/overview");
  const corp = useGet<Corporate>("/agency/corporate");
  const holds = useGet<{ holds: Hold[] }>("/escrow/holds");
  const fw = useGet<FirewallState>("/firewall/state");

  const m = ov.data?.metrics;
  const currency = m?.currency ?? "MYR";
  const held = (holds.data?.holds ?? []).reduce((s, h) => s + (h.amount - h.released - h.refunded), 0);
  const unhealthy = (fw.data?.listings ?? []).filter((l) => !l.healthy).length;

  const [seeding, setSeeding] = useState(false);
  const prepareDemo = async () => {
    setSeeding(true);
    try { await api.post("/demo/seed", {}); toast.success("Demo data ready — every panel is populated."); }
    catch { toast.error("Could not seed demo data"); } finally { setSeeding(false); }
  };

  return (
    <div>
      <div className="mb-2 flex items-start justify-between gap-3">
        <PageHead icon={TrendingUp} title="Agency console" subtitle="Your agents book, monitor and settle direct — bypassing the OTAs." />
        <Button size="sm" variant="secondary" onClick={prepareDemo} loading={seeding}><Sparkles className="h-3.5 w-3.5" /> Prepare demo data</Button>
      </div>

      <Card className="mb-4 border-l-4 border-[var(--success)]">
        <p className="text-xs uppercase tracking-wide text-[var(--muted)]">OTA commission avoided</p>
        <p className="mt-1 text-4xl font-bold text-[var(--success)]">
          <Money amount={m?.total_saved ?? 0} currency={currency} />
        </p>
        <p className="mt-1 text-sm text-[var(--muted)]">
          across {m?.managed_trips ?? 0} managed trips — booked direct via Atlas/NDC, no middleman cut.
        </p>
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Managed trips" value={m?.managed_trips ?? 0} />
        <Stat label="Escrow held" value={<Money amount={held} currency={currency} />} />
        <Stat label="Travellers at risk" value={corp.data?.duty_of_care.at_risk ?? 0} tone={(corp.data?.duty_of_care.at_risk ?? 0) > 0 ? "warning" : "success"} />
        <Stat label="Inventory alerts" value={unhealthy} tone={unhealthy > 0 ? "warning" : "success"} />
        <Stat label="Policy breaches" value={corp.data?.policy_violations ?? 0} tone={(corp.data?.policy_violations ?? 0) > 0 ? "warning" : "success"} />
        <Stat label="Fleet CO₂ (kg)" value={(corp.data?.esg.total_co2_kg ?? 0).toLocaleString()} />
        <Stat label="Trips measured" value={corp.data?.esg.trips_measured ?? 0} />
        <Stat label="Policy" value={corp.data?.policy.configured ? "On" : "Off"} tone={corp.data?.policy.configured ? "success" : "brand"} />
      </div>

      <p className="mt-6 text-sm text-[var(--muted)]">
        Use the left rail: run disruption ops, guard hotel inventory, and let the AI adjudicator settle escrow.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------ Disruptions */

type WatchAlt = { id: string; title: string; price_amount: number | null; price_currency: string | null; within_budget: boolean | null };
type Watch = {
  disrupted: boolean; reason?: string;
  status?: { status: string; delay_minutes: number | null; carrier?: string; route?: string; mode: string };
  recovery?: { summary: string; additional_cost: string }; notified?: boolean;
  alternatives?: WatchAlt[]; budget?: { amount: number | null; currency: string; within_budget_count: number; total_alternatives: number };
};
type GraphNode = { id: string; kind: string; day: number; title: string; starts_at?: string; shift_minutes?: number; conflict?: string | null };
type Replan = {
  error?: string; source: string; delay_minutes: number;
  graph: { nodes: GraphNode[] }; impacted: GraphNode[];
  rebook: { summary: string; additional_cost: string };
  settlement: { direction: string; fare_delta: number | null; currency: string; mode?: string };
};

export function ConsoleDisruptions() {
  const [mode, setMode] = useState("delayed");
  const [auto, setAuto] = useState(true);
  const [watch, setWatch] = useState<Watch | null>(null);
  const [wLoading, setWLoading] = useState(false);
  const [replan, setReplan] = useState<Replan | null>(null);
  const [rLoading, setRLoading] = useState(false);

  const runWatch = async () => {
    setWLoading(true);
    try {
      setWatch(await api.post<Watch>("/monitor/flight", { simulate: mode === "real" ? null : mode, auto_reschedule: auto, threshold_minutes: 90 }));
    } catch { toast.error("Status check failed"); } finally { setWLoading(false); }
  };
  const runReplan = async () => {
    setRLoading(true);
    try {
      const r = await api.post<Replan>("/itinerary/replan", { event_type: "flight_delayed", delay_minutes: 200, persist: false });
      if (r.error) toast.info(r.error); else setReplan(r);
    } catch { toast.error("Re-plan failed"); } finally { setRLoading(false); }
  };

  const s = watch?.status;
  const b = watch?.budget;
  return (
    <div>
      <PageHead icon={Plane} title="Trip operations" subtitle="Your agents monitor every managed traveller's flight; if one is disrupted they auto-rebook within budget and cascade the itinerary. Use a drill to watch the agent work." />

      <Card className="mb-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Zap className="h-4 w-4 text-[var(--brand-500)]" /> Flight watch &amp; auto-reschedule <span className="ml-2 rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--success)_16%,transparent)] px-2 py-0.5 text-[0.65rem] font-medium text-[var(--success)]">monitoring on</span></div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="w-48"><Select value={mode} onValueChange={setMode} options={[{ value: "real", label: "Check live status" }, { value: "delayed", label: "Demo: delay" }, { value: "cancelled", label: "Demo: cancellation" }]} aria-label="mode" /></div>
          <label className="flex items-center gap-2 text-sm"><Switch checked={auto} onCheckedChange={setAuto} aria-label="auto" /> Auto-reschedule</label>
          <Button onClick={runWatch} loading={wLoading} disabled={wLoading}><Zap className="h-4 w-4" /> Check now</Button>
        </div>
        {watch && (
          <div className="mt-4">
            {watch.reason ? <p className="text-sm text-[var(--muted)]">{watch.reason}</p>
              : !watch.disrupted ? (
                <div className="flex items-center gap-2 rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--success)_12%,transparent)] px-3 py-2 text-sm text-[var(--success)]">
                  <CheckCircle2 className="h-4 w-4" /> {s?.carrier} {s?.route} is {s?.status?.replace(/_/g, " ")}{s?.mode === "simulated" ? " (simulated)" : ""}.
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="rounded-[var(--r-md)] border-l-4 border-[var(--warning)] bg-[color-mix(in_srgb,var(--warning)_10%,transparent)] px-4 py-3">
                    <div className="flex items-center gap-2 text-sm font-semibold">
                      <AlertTriangle className="h-4 w-4 text-[var(--warning)]" /> {s?.carrier} {s?.route} {s?.status?.toUpperCase()}{s?.delay_minutes ? ` · ~${s.delay_minutes} min` : ""}
                      {watch.notified && <Badge variant="success">Alerted</Badge>}
                    </div>
                    <p className="mt-1 text-sm text-[var(--muted)]">{watch.recovery?.summary} · {watch.recovery?.additional_cost}</p>
                  </div>
                  {b?.amount != null && <p className="text-xs text-[var(--muted)]">{b.within_budget_count}/{b.total_alternatives} alternatives within {b.currency} {b.amount.toLocaleString()}</p>}
                  <div className="grid gap-2 sm:grid-cols-2">
                    {(watch.alternatives ?? []).map((a) => (
                      <div key={a.id} className="surface-card flex items-center justify-between gap-2 p-3">
                        <span className="min-w-0 truncate text-sm">{a.title}</span>
                        {a.price_amount != null && <span className={cn("shrink-0 text-sm font-semibold", a.within_budget ? "text-[var(--success)]" : "text-[var(--warning)]")}><Money amount={a.price_amount} currency={a.price_currency ?? "MYR"} /></span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
          </div>
        )}
      </Card>

      <Card>
        <div className="mb-1 flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 text-[var(--brand-500)]" /> Itinerary dependency graph</div>
        <p className="mb-3 text-sm text-[var(--muted)]">A delay to one leg cascades downstream. We re-plan every broken leg and settle the fare difference in real time.</p>
        <Button variant="secondary" onClick={runReplan} loading={rLoading} disabled={rLoading}>Simulate 200-min delay &amp; auto-replan</Button>
        {replan && (
          <div className="mt-4 space-y-4">
            <div className="rounded-[var(--r-md)] bg-[var(--bg)] p-3 text-sm">
              <strong>Cascade:</strong> {replan.rebook.summary} · fare {replan.settlement.direction === "refund" ? "refund" : replan.settlement.direction === "upcharge" ? "top-up" : "unchanged"}
              {replan.settlement.fare_delta != null ? ` ${replan.settlement.currency} ${Math.abs(replan.settlement.fare_delta).toLocaleString()}` : ""}
              {replan.settlement.mode ? ` (${replan.settlement.mode})` : ""}
            </div>
            <div>
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">Legs ({replan.graph.nodes.length}) — impacted highlighted</p>
              <div className="space-y-1">
                {replan.graph.nodes.map((n) => {
                  const broken = replan.impacted.some((i) => i.id === n.id);
                  return (
                    <div key={n.id} className={cn("flex items-center gap-2 rounded-[var(--r-md)] px-3 py-1.5 text-sm", broken ? "bg-[color-mix(in_srgb,var(--warning)_12%,transparent)]" : "bg-[var(--bg)]")}>
                      <LegDot kind={n.kind} />
                      <span className="w-10 shrink-0 text-xs text-[var(--muted)]">D{n.day}</span>
                      <span className="w-14 shrink-0 text-xs tabular-nums text-[var(--muted)]">{n.starts_at ?? "—"}</span>
                      <span className="min-w-0 flex-1 truncate">{n.title}</span>
                      {n.conflict && <Badge variant="warning">{n.conflict.replace(/_/g, " ")}</Badge>}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function LegDot({ kind }: { kind: string }) {
  const label: Record<string, string> = { flight: "✈", hotel: "🏨", activity: "◆", meal: "🍽", transport: "🚌" };
  return <span className="w-5 shrink-0 text-center text-xs">{label[kind] ?? "◆"}</span>;
}

/* -------------------------------------------------------------- Firewall */

type Channel = { channel: string; allocated: number; sold: number };
type FwListing = { listing_id: string; title: string; property: string; capacity: number; physical_available: number; total_allocated: number; healthy: boolean; channels: Channel[]; discrepancies: { type: string; detail: string; severity?: string }[] };
type Race = { error?: string; double_booking_prevented: boolean; summary: string; attempts: { channel: string; status: string; reason?: string }[] };

export function ConsoleFirewall() {
  const { data, loading, reload } = useGet<{ listings: FwListing[] }>("/firewall/state");
  const [busy, setBusy] = useState("");
  const [race, setRace] = useState<Race | null>(null);

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    try { await fn(); await reloadAfter(); } catch { toast.error(`${label} failed`); } finally { setBusy(""); }
  };
  const reloadAfter = async () => { reload(); };

  const seed = () => act("seed", async () => { await api.post("/firewall/seed", {}); toast.success("Demo inventory seeded"); });
  const reconcile = () => act("reconcile", async () => { const r = await api.post<{ count: number }>("/firewall/reconcile", {}); toast.success(`${r.count} fix(es) applied`); });
  const simulate = (id: string) => act("race", async () => { const r = await api.post<Race>("/firewall/simulate-race", { listing_id: id }); setRace(r); if (!r.error) toast[r.double_booking_prevented ? "success" : "error"](r.summary); });

  const listings = data?.listings ?? [];
  return (
    <div>
      <PageHead icon={ShieldCheck} title="Inventory firewall" subtitle="Every booking passes an atomic guard so two channels can never sell the same room. Auto-guard is always on — reconcile drift, or run a drill to watch it block a double-booking." />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--success)_16%,transparent)] px-2.5 py-1 text-xs font-medium text-[var(--success)]">Auto-guard ON</span>
        <Button variant="secondary" onClick={reconcile} loading={busy === "reconcile"}>Reconcile channels</Button>
        <Button variant="ghost" onClick={seed} loading={busy === "seed"}>Load sample inventory</Button>
      </div>

      {loading ? <p className="text-sm text-[var(--muted)]">Loading…</p>
        : !listings.length ? <Card><p className="text-sm text-[var(--muted)]">No listings yet — click <strong>Seed demo inventory</strong> to create an over-allocated room.</p></Card>
          : listings.map((l) => (
            <Card key={l.listing_id} className="mb-3">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="font-semibold">{l.title}</span>
                <span className="text-xs text-[var(--muted)]">{l.property}</span>
                {l.healthy ? <Badge variant="success">healthy</Badge> : <Badge variant="warning">{l.discrepancies.length} issue(s)</Badge>}
                <span className="ml-auto text-xs text-[var(--muted)]">cap {l.capacity} · allocated {l.total_allocated} · available {l.physical_available}</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-xs uppercase tracking-wide text-[var(--muted)]"><th className="py-1 pr-4">Channel</th><th className="py-1 pr-4">Allocated</th><th className="py-1 pr-4">Sold</th><th className="py-1">Open</th></tr></thead>
                  <tbody>
                    {l.channels.map((c) => (
                      <tr key={c.channel} className="border-t border-[var(--border)]"><td className="py-1.5 pr-4">{c.channel}</td><td className="py-1.5 pr-4">{c.allocated}</td><td className="py-1.5 pr-4">{c.sold}</td><td className="py-1.5">{c.allocated - c.sold}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {l.discrepancies.map((d, i) => (
                <p key={i} className="mt-2 flex items-start gap-1.5 text-xs text-[var(--warning)]"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {d.detail}</p>
              ))}
              <div className="mt-3">
                <Button size="sm" variant="danger" onClick={() => simulate(l.listing_id)} loading={busy === "race"}>Run drill: two channels, one room</Button>
              </div>
              {race && !race.error && (
                <div className="mt-3 rounded-[var(--r-md)] bg-[var(--bg)] p-3 text-sm">
                  <p className="font-medium">{race.double_booking_prevented ? "✅ Double-booking prevented" : "⚠️ Check config"} — {race.summary}</p>
                  {race.attempts.map((a, i) => (
                    <p key={i} className={cn("text-xs", a.status === "confirmed" ? "text-[var(--success)]" : "text-[var(--warning)]")}>{a.channel}: {a.status}{a.reason ? ` — ${a.reason}` : ""}</p>
                  ))}
                </div>
              )}
            </Card>
          ))}
    </div>
  );
}

/* ---------------------------------------------------------------- Escrow */

type LedgerEvent = { kind: string; amount: number; currency: string; actor: string; reason: string; settlement: string };
type FullHold = Hold & { events?: LedgerEvent[] };
type Decision = { verdict: string; refund_pct: number; refund_amount: number; release_amount: number; currency: string; rationale: string; policy_basis: string };

export function ConsoleEscrow() {
  const { data, loading, reload } = useGet<{ holds: Hold[] }>("/escrow/holds");
  const [event, setEvent] = useState("flight_delayed");
  const [delay, setDelay] = useState("200");
  const [busy, setBusy] = useState(false);
  const [decision, setDecision] = useState<{ decision: Decision; hold: FullHold } | null>(null);

  const holds = data?.holds ?? [];

  const openHold = async () => {
    setBusy(true);
    try { await api.post("/escrow/hold", { from_active_trip: true }); toast.success("Escrow hold opened from active trip"); reload(); }
    catch { toast.error("Could not open a hold — plan & save a trip first"); } finally { setBusy(false); }
  };
  const adjudicate = async (holdId: string) => {
    setBusy(true);
    try {
      const r = await api.post<{ error?: string; decision: Decision; hold: FullHold }>("/escrow/adjudicate", { hold_id: holdId, event_type: event, delay_minutes: event.includes("delay") ? Number(delay) : null });
      if (r.error) { toast.info(r.error); return; }
      setDecision(r); reload(); toast.success(`AI verdict: ${r.decision.verdict.replace(/_/g, " ")}`);
    } catch { toast.error("Adjudication failed"); } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHead icon={CreditCard} title="Escrow & AI refunds" subtitle="Funds held on booking; an agent adjudicates disputes and settles autonomously." />

      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <Button variant="secondary" onClick={openHold} loading={busy}>Open hold from active trip</Button>
          <div className="w-48"><Select value={event} onValueChange={setEvent} options={[{ value: "flight_delayed", label: "Flight delayed" }, { value: "flight_cancelled", label: "Flight cancelled" }, { value: "downgrade", label: "Downgrade" }, { value: "no_show", label: "No-show" }, { value: "service_issue", label: "Service issue" }]} aria-label="event" /></div>
          {event.includes("delay") && <div className="w-28"><Select value={delay} onValueChange={setDelay} options={[{ value: "90", label: "90 min" }, { value: "150", label: "150 min" }, { value: "200", label: "200 min" }, { value: "300", label: "300 min" }, { value: "400", label: "400 min" }]} aria-label="delay" /></div>}
        </div>
        <p className="mt-2 text-xs text-[var(--muted)]">Pick a hold below and press <strong>Adjudicate</strong> — the agent decides the refund/release split and settles it.</p>
      </Card>

      {decision && (
        <Card className="mb-4 border-l-4 border-[var(--brand-500)]">
          <div className="mb-1 flex items-center gap-2"><Badge variant="brand">AI verdict</Badge><span className="text-sm font-semibold capitalize">{decision.decision.verdict.replace(/_/g, " ")} · {decision.decision.refund_pct}% refund</span></div>
          <p className="text-sm">Refund <strong><Money amount={decision.decision.refund_amount} currency={decision.decision.currency} /></strong> to traveller · release <strong><Money amount={decision.decision.release_amount} currency={decision.decision.currency} /></strong> to supplier.</p>
          <p className="mt-2 text-sm text-[var(--muted)]">{decision.decision.rationale}</p>
          <p className="mt-1 text-xs text-[var(--muted)]"><strong>Basis:</strong> {decision.decision.policy_basis}</p>
        </Card>
      )}

      {loading ? <p className="text-sm text-[var(--muted)]">Loading…</p>
        : !holds.length ? <Card><p className="text-sm text-[var(--muted)]">No escrow holds yet — open one from your active trip above.</p></Card>
          : (
            <div className="space-y-2">
              {holds.map((h) => (
                <Card key={h.id} className="flex flex-wrap items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{h.description || h.booking_ref}</p>
                    <p className="text-xs text-[var(--muted)]">held <Money amount={h.amount} currency={h.currency} /> · refunded <Money amount={h.refunded} currency={h.currency} /> · released <Money amount={h.released} currency={h.currency} /></p>
                  </div>
                  <Badge variant={h.status === "held" ? "brand" : h.status === "refunded" ? "warning" : "success"}>{h.status}</Badge>
                  <Button size="sm" onClick={() => adjudicate(h.id)} loading={busy}>Adjudicate</Button>
                </Card>
              ))}
            </div>
          )}
    </div>
  );
}

/* --------------------------------------------------------------- Policy */

type Traveller = { trip_id: string; destination: string; safety_level: string };
type CorpFull = {
  policy: { configured: boolean; max_fare_amount: number | null; fare_currency: string; max_cabin: string | null; preferred_carriers: string[]; max_hotel_per_night: number | null };
  policy_violations: number;
  duty_of_care: { travellers: Traveller[]; at_risk: number };
  esg: { total_co2_kg: number; total_offset_usd: number; trips_measured: number };
};

export function ConsolePolicy() {
  const { data, loading } = useGet<CorpFull>("/agency/corporate");
  const p = data?.policy;
  return (
    <div>
      <PageHead icon={FileCheck2} title="Policy, duty of care & ESG" subtitle="Corporate controls the agents enforce on every search + fleet risk and carbon." />
      {loading ? <p className="text-sm text-[var(--muted)]">Loading…</p> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold">Travel policy {data && data.policy_violations > 0 ? <Badge variant="warning">{data.policy_violations} flagged</Badge> : p?.configured ? <Badge variant="success">compliant</Badge> : null}</div>
            {!p?.configured ? <p className="text-sm text-[var(--muted)]">No policy set — upload one in the assistant (📎) and the flight/hotel agents will enforce it.</p>
              : (
                <div className="flex flex-wrap gap-2 text-xs">
                  {p.max_fare_amount != null && <Chip>Fare cap {p.fare_currency} {p.max_fare_amount.toLocaleString()}</Chip>}
                  {p.max_cabin && <Chip>Max cabin: {p.max_cabin.replace(/_/g, " ")}</Chip>}
                  {p.max_hotel_per_night != null && <Chip>Hotel ≤ {p.max_hotel_per_night.toLocaleString()}/night</Chip>}
                  {p.preferred_carriers.slice(0, 5).map((c) => <Chip key={c}>✈ {c}</Chip>)}
                </div>
              )}
          </Card>
          <Card>
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><ShieldCheck className="h-4 w-4 text-[var(--brand-500)]" /> Duty of care {data && <span className="ml-auto text-xs text-[var(--muted)]">{data.duty_of_care.at_risk} need attention</span>}</div>
            {!data?.duty_of_care.travellers.length ? <p className="text-sm text-[var(--muted)]">No trips with safety data yet.</p>
              : <div className="space-y-1.5">{data.duty_of_care.travellers.slice(0, 8).map((t) => (
                <div key={t.trip_id} className="flex items-center gap-2 text-sm"><RiskPill level={t.safety_level} /><span className="truncate">{t.destination}</span></div>
              ))}</div>}
          </Card>
          <Card className="lg:col-span-2">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Leaf className="h-4 w-4 text-[var(--success)]" /> ESG · carbon</div>
            {!data?.esg.trips_measured ? <p className="text-sm text-[var(--muted)]">Carbon appears once trips run the sustainability agent.</p>
              : <div className="grid grid-cols-3 gap-3">
                <Stat label="Flight CO₂ (kg)" value={data.esg.total_co2_kg.toLocaleString()} />
                <Stat label="Offset cost" value={<Money amount={data.esg.total_offset_usd} currency="USD" />} />
                <Stat label="Trips measured" value={data.esg.trips_measured} />
              </div>}
          </Card>
        </div>
      )}
    </div>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return <span className="rounded-[var(--r-pill)] border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1">{children}</span>;
}

/* -------------------------------------------------------------- Clients */

type Client = { id: string; name: string; email: string | null; telegram_chat_id: string | null; whatsapp: string | null; channel: string; notes: string | null; source?: string; destination?: string | null; share_token?: string | null };
type ClientRun = { dest: string; jobId?: string; status?: string; share_url?: string; delivered?: boolean; detail?: string };

async function pollJob(id: string): Promise<string> {
  for (let i = 0; i < 100; i++) {
    try {
      const r = await api.get<{ status?: string }>(`/jobs/${id}`);
      const s = r.status ?? "";
      if (["done", "completed", "failed", "error"].includes(s)) return s;
    } catch { /* keep polling */ }
    await new Promise((res) => setTimeout(res, 3000));
  }
  return "timeout";
}

export function ConsoleClients() {
  const { data, loading, reload } = useGet<{ clients: Client[] }>("/agency/clients");
  const [form, setForm] = useState({ name: "", email: "", telegram_chat_id: "", whatsapp: "", channel: "telegram", notes: "" });
  const [adding, setAdding] = useState(false);
  const [runs, setRuns] = useState<Record<string, ClientRun>>({});
  const [busy, setBusy] = useState("");

  const clients = data?.clients ?? [];
  const setRun = (id: string, patch: Partial<ClientRun>) => setRuns((r) => ({ ...r, [id]: { ...(r[id] ?? { dest: "" }), ...patch } }));

  const addClient = async () => {
    if (!form.name.trim()) return toast.info("Name is required.");
    setAdding(true);
    try { await api.post("/agency/clients", form); toast.success("Client added"); setForm({ name: "", email: "", telegram_chat_id: "", whatsapp: "", channel: "telegram", notes: "" }); reload(); }
    catch { toast.error("Could not add client"); } finally { setAdding(false); }
  };
  const buildPackage = async (id: string) => {
    const dest = runs[id]?.dest?.trim();
    if (!dest) return toast.info("Enter a destination first.");
    setBusy("plan:" + id); setRun(id, { status: "running", share_url: undefined });
    try {
      const r = await api.post<{ job?: { id: string } }>(`/agency/clients/${id}/plan`, { destination: dest });
      const jid = r.job?.id;
      if (!jid) throw new Error("no job");
      setRun(id, { jobId: jid });
      const status = await pollJob(jid);
      setRun(id, { status });
      toast[status === "done" ? "success" : "info"](status === "done" ? "Package ready — compile & send" : `Plan ${status}`);
    } catch { toast.error("Planning failed"); setRun(id, { status: "error" }); } finally { setBusy(""); }
  };
  const deliverPackage = async (id: string) => {
    const jobId = runs[id]?.jobId;
    if (!jobId) return;
    setBusy("deliver:" + id);
    try {
      const r = await api.post<{ error?: string; share_url?: string; delivered?: boolean; deliveries?: { channel: string; ok: boolean; detail: string }[] }>("/agency/deliver", { client_id: id, job_id: jobId });
      if (r.error) { toast.info(r.error); return; }
      const detail = (r.deliveries ?? []).map((d) => `${d.channel}: ${d.ok ? "sent" : d.detail}`).join(" · ");
      setRun(id, { share_url: r.share_url, delivered: r.delivered, detail });
      toast[r.delivered ? "success" : "info"](r.delivered ? "Delivered to client" : "PDF + link ready");
    } catch { toast.error("Delivery failed"); } finally { setBusy(""); }
  };

  return (
    <div>
      <PageHead icon={Sparkles} title="Clients" subtitle="Plan a full package for a client, then send the PDF + an interactive link over Telegram." />

      <PackagePageCard />

      <Card className="mb-4">
        <div className="mb-3 text-sm font-semibold">Add a client</div>
        <div className="grid gap-2 sm:grid-cols-2">
          <input className={inputCls} placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className={inputCls} placeholder="Email (optional)" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input className={inputCls} placeholder="Telegram chat id" value={form.telegram_chat_id} onChange={(e) => setForm({ ...form, telegram_chat_id: e.target.value })} />
          <input className={inputCls} placeholder="WhatsApp number (e.g. 60123456789)" value={form.whatsapp} onChange={(e) => setForm({ ...form, whatsapp: e.target.value })} />
          <Select value={form.channel} onValueChange={(v) => setForm({ ...form, channel: v })} options={[{ value: "telegram", label: "Deliver via Telegram" }, { value: "whatsapp", label: "Deliver via WhatsApp" }, { value: "both", label: "Telegram + WhatsApp" }]} aria-label="channel" />
          <input className={inputCls} placeholder="Notes (party size, prefs)" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>
        <div className="mt-2"><Button onClick={addClient} loading={adding}>Add client</Button></div>
      </Card>

      {loading ? <p className="text-sm text-[var(--muted)]">Loading…</p>
        : !clients.length ? <Card><p className="text-sm text-[var(--muted)]">No clients yet — add one above.</p></Card>
          : clients.map((c) => {
            const run = runs[c.id] ?? { dest: "" };
            return (
              <Card key={c.id} className="mb-3">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{c.name}</span>
                  <Badge variant="brand">via {c.channel}</Badge>
                  {c.source === "package_page" && <Badge variant="success">🌐 from planning page</Badge>}
                  {c.destination && <Badge>{c.destination}</Badge>}
                  {(c.channel !== "whatsapp" && !c.telegram_chat_id) && <Badge variant="warning">no Telegram id</Badge>}
                  {(c.channel !== "telegram" && !c.whatsapp) && <Badge variant="warning">no WhatsApp</Badge>}
                  {c.notes && <span className="text-xs text-[var(--muted)]">{c.notes}</span>}
                </div>
                {c.share_token && (
                  <p className="mb-2 text-xs">
                    Auto-drafted package:{" "}
                    <a href={`/s/${c.share_token}`} target="_blank" rel="noreferrer" className="text-[var(--brand-600)] underline">
                      view the plan our agents built
                    </a>
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <input className={cn(inputCls, "max-w-[16rem]")} placeholder="Destination (e.g. Langkawi)" value={run.dest} onChange={(e) => setRun(c.id, { dest: e.target.value })} />
                  <Button size="sm" onClick={() => buildPackage(c.id)} loading={busy === "plan:" + c.id}><Sparkles className="h-3.5 w-3.5" /> Build full package</Button>
                  {run.status === "done" && <Button size="sm" variant="secondary" onClick={() => deliverPackage(c.id)} loading={busy === "deliver:" + c.id}>Compile &amp; send</Button>}
                </div>
                {run.status && run.status !== "done" && <p className="mt-2 text-xs text-[var(--muted)]">{run.status === "running" ? "Agents are building the package…" : `Plan ${run.status}`}</p>}
                {run.share_url && (
                  <div className="mt-2 rounded-[var(--r-md)] bg-[var(--bg)] p-3 text-sm">
                    <p>{run.delivered ? "✅ Sent to the client on Telegram." : `PDF ready — Telegram: ${run.detail}`}</p>
                    <p className="mt-1 text-xs">Interactive link: <a href={run.share_url} target="_blank" rel="noreferrer" className="text-[var(--brand-600)] underline">{run.share_url}</a></p>
                  </div>
                )}
              </Card>
            );
          })}
    </div>
  );
}

type PackagePage = { token: string; org_name: string | null; headline: string | null; subhead: string | null; enabled: boolean; url: string };

/** The agency's public lead-capture page: share the link, prospects self-serve a
 *  trip request, and the mesh auto-drafts a package that lands as a lead. */
function PackagePageCard() {
  const { data, loading, reload } = useGet<{ page: PackagePage }>("/agency/package-page");
  const page = data?.page;
  const [busy, setBusy] = useState(false);
  const [headline, setHeadline] = useState("");
  useEffect(() => { if (page?.headline != null) setHeadline(page.headline); }, [page?.headline]);

  const save = async (patch: Partial<PackagePage>) => {
    setBusy(true);
    try { await api.post("/agency/package-page", { headline, ...patch }); reload(); }
    catch { toast.error("Couldn't update the page."); } finally { setBusy(false); }
  };

  if (loading || !page) return null;
  return (
    <Card className="mb-4 border-[var(--brand-400)]/40">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-sm font-semibold">🌐 Your public planning page</div>
        <Button size="sm" variant={page.enabled ? "secondary" : "primary"} loading={busy} onClick={() => save({ enabled: !page.enabled })}>
          {page.enabled ? "Enabled" : "Enable"}
        </Button>
      </div>
      <p className="mb-2 text-xs text-[var(--muted)]">
        Share this link with prospects — they describe their trip on a branded page and your AI agents auto-draft a full package. Each request becomes a lead below.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input readOnly className={cn(inputCls, "min-w-0 flex-1 font-[family-name:var(--font-mono)] text-xs")} value={page.url} />
        <Button size="sm" variant="secondary" onClick={() => { void navigator.clipboard?.writeText(page.url); toast.success("Link copied"); }}>Copy link</Button>
        <a href={page.url} target="_blank" rel="noreferrer" className="text-xs text-[var(--brand-600)] underline">Open</a>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input className={cn(inputCls, "min-w-0 flex-1")} placeholder="Headline shown to clients" value={headline} onChange={(e) => setHeadline(e.target.value)} />
        <Button size="sm" variant="secondary" loading={busy} onClick={() => void save({})}>Save</Button>
      </div>
    </Card>
  );
}

/* --------------------------------------------------------------- Finance */

type Tx = { id: string; kind: string; amount: number; currency: string; status: string; counterparty: string | null; description: string | null; reference: string | null; created_at: string };
type FinSummary = { currency: string; income: number; refunds: number; payouts: number; net: number; count: number };

const KIND_TONE: Record<string, "success" | "warning" | "brand" | "default"> = { income: "success", refund: "warning", payout: "brand", fee: "brand", adjustment: "default" };

async function openReceipt(id: string) {
  const token = getAccessToken();
  const res = await fetch(`${API_BASE}/finance/receipt/${id}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) return toast.error("Receipt unavailable");
  const url = URL.createObjectURL(await res.blob());
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

export function ConsoleFinance() {
  const [filters, setFilters] = useState({ kind: "", status: "", q: "" });
  const [rows, setRows] = useState<Tx[]>([]);
  const [sum, setSum] = useState<FinSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [ai, setAi] = useState<{ summary: string; highlights: string[] } | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [sort, setSort] = useState<{ key: "created_at" | "amount"; dir: 1 | -1 }>({ key: "created_at", dir: -1 });

  const load = useCallback(async () => {
    setLoading(true);
    const qs = new URLSearchParams();
    if (filters.kind) qs.set("kind", filters.kind);
    if (filters.status) qs.set("status", filters.status);
    if (filters.q) qs.set("q", filters.q);
    try {
      const [t, s] = await Promise.all([
        api.get<{ transactions: Tx[] }>(`/finance/transactions?${qs.toString()}`),
        api.get<FinSummary>("/finance/summary"),
      ]);
      setRows(t.transactions);
      setSum(s);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [filters]);
  useEffect(() => { load(); }, [load]);

  const aiSummarize = async () => {
    setAiBusy(true);
    try { setAi(await api.post<{ summary: string; highlights: string[] }>("/finance/ai-summary", {})); }
    catch { toast.error("AI summary failed"); } finally { setAiBusy(false); }
  };

  const sorted = [...rows].sort((a, b) =>
    sort.key === "amount" ? (a.amount - b.amount) * sort.dir : (a.created_at < b.created_at ? -1 : 1) * sort.dir,
  );
  const toggleSort = (key: "created_at" | "amount") =>
    setSort((s) => ({ key, dir: s.key === key && s.dir === -1 ? 1 : -1 }));

  const cur = sum?.currency ?? "MYR";
  return (
    <div>
      <PageHead icon={CreditCard} title="Finance" subtitle="Every money movement in one ledger — bookings, refunds, payouts — with a receipt on each and an AI readout." />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Income" value={<Money amount={sum?.income ?? 0} currency={cur} />} tone="success" />
        <Stat label="Refunds" value={<Money amount={sum?.refunds ?? 0} currency={cur} />} tone="warning" />
        <Stat label="Payouts / fees" value={<Money amount={sum?.payouts ?? 0} currency={cur} />} />
        <Stat label="Net" value={<Money amount={sum?.net ?? 0} currency={cur} />} tone="brand" />
      </div>

      <Card className="mb-4">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 text-[var(--brand-500)]" /> AI finance summary</div>
          <Button size="sm" variant="secondary" onClick={aiSummarize} loading={aiBusy}>Summarise</Button>
        </div>
        {ai && (
          <div className="mt-3 text-sm">
            <p className="text-[var(--text)]">{ai.summary}</p>
            {!!ai.highlights.length && (
              <ul className="mt-2 space-y-1 text-[var(--muted)]">{ai.highlights.map((h, i) => <li key={i}>• {h}</li>)}</ul>
            )}
          </div>
        )}
      </Card>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-40"><Select value={filters.kind || "all"} onValueChange={(v) => setFilters({ ...filters, kind: v === "all" ? "" : v })} options={[{ value: "all", label: "All kinds" }, { value: "income", label: "Income" }, { value: "refund", label: "Refunds" }, { value: "payout", label: "Payouts" }, { value: "fee", label: "Fees" }]} aria-label="kind" /></div>
        <input className={cn(inputCls, "max-w-[16rem]")} placeholder="Search party / description / ref" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
        <span className="ml-auto text-xs text-[var(--muted)]">{sorted.length} transaction(s)</span>
      </div>

      <Card className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-left text-xs uppercase tracking-wide text-[var(--muted)]">
              <th className="cursor-pointer px-4 py-2" onClick={() => toggleSort("created_at")}>Date {sort.key === "created_at" ? (sort.dir === -1 ? "↓" : "↑") : ""}</th>
              <th className="px-4 py-2">Kind</th>
              <th className="px-4 py-2">Party</th>
              <th className="px-4 py-2">Description</th>
              <th className="cursor-pointer px-4 py-2 text-right" onClick={() => toggleSort("amount")}>Amount {sort.key === "amount" ? (sort.dir === -1 ? "↓" : "↑") : ""}</th>
              <th className="px-4 py-2 text-right">Receipt</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-[var(--muted)]">Loading…</td></tr>
            ) : !sorted.length ? (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-[var(--muted)]">No transactions yet — take a booking and it lands here.</td></tr>
            ) : sorted.map((t) => (
              <tr key={t.id} className="border-b border-[var(--border)] last:border-0">
                <td className="whitespace-nowrap px-4 py-2 text-xs text-[var(--muted)]">{(t.created_at || "").slice(0, 10)}</td>
                <td className="px-4 py-2"><Badge variant={KIND_TONE[t.kind] ?? "default"}>{t.kind}</Badge></td>
                <td className="px-4 py-2">{t.counterparty || "—"}</td>
                <td className="max-w-[22rem] truncate px-4 py-2 text-[var(--muted)]">{t.description || "—"}</td>
                <td className={cn("whitespace-nowrap px-4 py-2 text-right font-semibold", t.kind === "refund" ? "text-[var(--warning)]" : "text-[var(--text)]")}>
                  {t.kind === "refund" ? "−" : ""}<Money amount={t.amount} currency={t.currency} />
                </td>
                <td className="px-4 py-2 text-right">
                  <button onClick={() => openReceipt(t.id)} className="inline-flex items-center gap-1 text-xs text-[var(--brand-600)] hover:underline"><Download className="h-3.5 w-3.5" /> PDF</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------- Bookings */

type Booking = { id: string; property_name: string; room_title: string; guest_name: string; channel: string; check_in: string | null; check_out: string | null; nights: number; amount: number; currency: string; status: string };
type CalDay = { room: string; guest: string; amount: number; currency: string };

export function ConsoleBookings() {
  const { data, loading, reload } = useGet<{ bookings: Booking[] }>("/bookings");
  const cal = useGet<{ days: Record<string, CalDay[]> }>("/bookings/calendar");
  const props = useGet<{ properties: SupplierProperty[] }>("/supplier/properties");
  const bookings = data?.bookings ?? [];
  const days = Object.entries(cal.data?.days ?? {}).sort(([a], [b]) => (a < b ? -1 : 1));

  const [form, setForm] = useState({ listing_id: "", guest_name: "", guest_contact: "", check_in: "", check_out: "" });
  const [busy, setBusy] = useState("");

  const listingOpts = (props.data?.properties ?? []).flatMap((p) =>
    (p.listings ?? []).map((l) => ({ value: l.id, label: `${p.name} — ${l.title}` })),
  );

  const createBooking = async () => {
    if (!form.listing_id || !form.guest_name.trim()) return toast.info("Pick a room and enter a guest name.");
    setBusy("book");
    try {
      const r = await api.post<{ status: string; reason?: string; amount?: number; currency?: string }>("/bookings", form);
      if (r.status === "blocked") toast.warning(r.reason ?? "Firewall blocked this booking.");
      else toast.success(`Booked — ${r.currency} ${r.amount?.toLocaleString()} · manager notified`);
      setForm({ listing_id: "", guest_name: "", guest_contact: "", check_in: "", check_out: "" });
      reload(); cal.reload();
    } catch { toast.error("Booking failed"); } finally { setBusy(""); }
  };
  const remind = async () => {
    setBusy("remind");
    try { const r = await api.post<{ sent: number }>("/bookings/remind-due", {}); toast.success(`${r.sent} check-in reminder(s) sent`); }
    catch { toast.error("Reminder sweep failed"); } finally { setBusy(""); }
  };

  return (
    <div>
      <PageHead icon={Building2} title="Bookings" subtitle="Direct reservations across channels — each one firewall-guarded, receipted, and posted to Finance." />

      {/* Quick booking */}
      <Card className="mb-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <span className="text-sm font-semibold">New booking</span>
          <Button size="sm" variant="secondary" onClick={remind} loading={busy === "remind"}><Calendar className="h-3.5 w-3.5" /> Send check-in reminders</Button>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <div><Select value={form.listing_id} onValueChange={(v) => setForm({ ...form, listing_id: v })} options={listingOpts.length ? listingOpts : [{ value: "", label: "No rooms — add one under Listings" }]} placeholder="Room" aria-label="room" /></div>
          <input className={inputCls} placeholder="Guest name" value={form.guest_name} onChange={(e) => setForm({ ...form, guest_name: e.target.value })} />
          <input className={inputCls} placeholder="Guest contact (email/phone)" value={form.guest_contact} onChange={(e) => setForm({ ...form, guest_contact: e.target.value })} />
          <div className="flex gap-2">
            <input type="date" className={inputCls} value={form.check_in} onChange={(e) => setForm({ ...form, check_in: e.target.value })} />
            <input type="date" className={inputCls} value={form.check_out} onChange={(e) => setForm({ ...form, check_out: e.target.value })} />
          </div>
        </div>
        <div className="mt-2"><Button onClick={createBooking} loading={busy === "book"}>Book &amp; notify</Button></div>
      </Card>

      <Card className="mb-4">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Calendar className="h-4 w-4 text-[var(--brand-500)]" /> Booking calendar</div>
        {!days.length ? <p className="text-sm text-[var(--muted)]">No dated bookings yet.</p>
          : (
            <div className="flex flex-wrap gap-2">
              {days.map(([d, list]) => (
                <div key={d} className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] p-3">
                  <p className="text-xs font-semibold text-[var(--brand-600)]">{d}</p>
                  {list.map((b, i) => (
                    <p key={i} className="mt-1 text-xs text-[var(--muted)]">{b.guest} · {b.room}</p>
                  ))}
                </div>
              ))}
            </div>
          )}
      </Card>

      <Card className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-left text-xs uppercase tracking-wide text-[var(--muted)]">
              <th className="px-4 py-2">Guest</th><th className="px-4 py-2">Room</th><th className="px-4 py-2">Dates</th>
              <th className="px-4 py-2">Channel</th><th className="px-4 py-2 text-right">Amount</th><th className="px-4 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {loading ? <tr><td colSpan={6} className="px-4 py-6 text-center text-[var(--muted)]">Loading…</td></tr>
              : !bookings.length ? <tr><td colSpan={6} className="px-4 py-6 text-center text-[var(--muted)]">No bookings yet.</td></tr>
                : bookings.map((b) => (
                  <tr key={b.id} className="border-b border-[var(--border)] last:border-0">
                    <td className="px-4 py-2 font-medium">{b.guest_name}</td>
                    <td className="px-4 py-2 text-[var(--muted)]">{b.room_title}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-xs text-[var(--muted)]">{b.check_in || "—"} → {b.check_out || "—"} ({b.nights}n)</td>
                    <td className="px-4 py-2 text-xs">{b.channel}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-right font-semibold"><Money amount={b.amount} currency={b.currency} /></td>
                    <td className="px-4 py-2"><Badge variant={b.status === "cancelled" ? "warning" : "success"}>{b.status}</Badge></td>
                  </tr>
                ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

/* ---------------------------------------------------------- Negotiation */

type NegTurn = { party: string; message: string; offer: number | null };
type NegDeal = { agreed: boolean; list_price: number; price: number | null; currency: string; perk: string | null; savings: number; room: string; property: string };
type NegResult = { error?: string; deal: NegDeal; transcript: NegTurn[]; booking: { status?: string; amount?: number; currency?: string } | null };
type Bid = { listing_id: string; property: string; room: string; list_price: number; bid: number; currency: string; perk: string; savings: number; winner: boolean; pitch: string };
type AuctionResult = { error?: string; headline: string; bids: Bid[]; winner: Bid; booking: { status?: string; amount?: number; currency?: string } | null };

export function ConsoleNegotiate() {
  const props = useGet<{ properties: SupplierProperty[] }>("/supplier/properties");
  const [mode, setMode] = useState<"single" | "auction">("single");
  const [form, setForm] = useState({ listing_id: "", guest_name: "Encik Rahman", traveller_ceiling: "", wants: "late checkout, sea view", nights: "2" });
  const [dest, setDest] = useState("Kota Kinabalu");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<NegResult | null>(null);
  const [auction, setAuction] = useState<AuctionResult | null>(null);

  const runAuction = async () => {
    if (!dest.trim()) return toast.info("Enter a destination.");
    setBusy(true);
    try {
      const r = await api.post<AuctionResult>("/negotiate/auction", {
        destination: dest, guest_name: form.guest_name,
        traveller_ceiling: form.traveller_ceiling ? Number(form.traveller_ceiling) : null,
        wants: form.wants, nights: Number(form.nights) || 1, auto_book: true,
      });
      if (r.error) { toast.info(r.error); return; }
      setAuction(r);
      toast.success(`${r.bids.length} hotels bid — ${r.winner.property} won`);
    } catch { toast.error("Auction failed"); } finally { setBusy(false); }
  };

  const listingOpts = (props.data?.properties ?? []).flatMap((p) =>
    (p.listings ?? []).filter((l) => l.price_amount != null).map((l) => ({ value: l.id, label: `${p.name} — ${l.title} (${l.price_currency} ${l.price_amount})` })),
  );

  const run = async () => {
    if (!form.listing_id) return toast.info("Pick a room to negotiate on.");
    setBusy(true);
    try {
      const r = await api.post<NegResult>("/negotiate", {
        listing_id: form.listing_id, guest_name: form.guest_name,
        traveller_ceiling: form.traveller_ceiling ? Number(form.traveller_ceiling) : null,
        wants: form.wants, nights: Number(form.nights) || 1, auto_book: true,
      });
      if (r.error) { toast.info(r.error); return; }
      setRes(r);
      toast[r.deal.agreed ? "success" : "info"](r.deal.agreed ? `Deal: ${r.deal.currency} ${r.deal.price}/night` : "No deal reached");
    } catch { toast.error("Negotiation failed"); } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHead icon={Sparkles} title="Rate negotiation" subtitle="AI agents settle a rate on their own — one-to-one, or let every hotel's agent bid for the guest." />

      <div className="mb-4 inline-flex gap-1 rounded-[var(--r-md)] bg-[var(--bg)] p-1 text-sm font-medium">
        {(["single", "auction"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)} className={cn("rounded-[calc(var(--r-md)-2px)] px-3 py-1.5", mode === m ? "bg-[var(--surface)] text-[var(--brand-600)] shadow-[var(--shadow-1)]" : "text-[var(--muted)]")}>
            {m === "single" ? "One room (1:1)" : "City auction (N hotels bid)"}
          </button>
        ))}
      </div>

      {mode === "single" ? (
        <Card className="mb-4">
          <div className="grid gap-2 sm:grid-cols-2">
            <Select value={form.listing_id} onValueChange={(v) => setForm({ ...form, listing_id: v })} options={listingOpts.length ? listingOpts : [{ value: "", label: "No priced rooms — add one under Listings" }]} placeholder="Room" aria-label="room" />
            <input className={inputCls} placeholder="Guest name" value={form.guest_name} onChange={(e) => setForm({ ...form, guest_name: e.target.value })} />
            <input className={inputCls} placeholder="Guest ceiling / night (optional)" value={form.traveller_ceiling} onChange={(e) => setForm({ ...form, traveller_ceiling: e.target.value })} />
            <input className={inputCls} placeholder="Nights" value={form.nights} onChange={(e) => setForm({ ...form, nights: e.target.value })} />
            <input className={cn(inputCls, "sm:col-span-2")} placeholder="Guest wants (perks)" value={form.wants} onChange={(e) => setForm({ ...form, wants: e.target.value })} />
          </div>
          <div className="mt-2"><Button onClick={run} loading={busy}><Sparkles className="h-4 w-4" /> Let the agents negotiate</Button></div>
        </Card>
      ) : (
        <Card className="mb-4">
          <div className="grid gap-2 sm:grid-cols-2">
            <input className={inputCls} placeholder="Destination (e.g. Kota Kinabalu)" value={dest} onChange={(e) => setDest(e.target.value)} />
            <input className={inputCls} placeholder="Guest name" value={form.guest_name} onChange={(e) => setForm({ ...form, guest_name: e.target.value })} />
            <input className={inputCls} placeholder="Guest ceiling / night (optional)" value={form.traveller_ceiling} onChange={(e) => setForm({ ...form, traveller_ceiling: e.target.value })} />
            <input className={inputCls} placeholder="Nights" value={form.nights} onChange={(e) => setForm({ ...form, nights: e.target.value })} />
          </div>
          <div className="mt-2"><Button onClick={runAuction} loading={busy}><Sparkles className="h-4 w-4" /> Broadcast — let the hotels bid</Button></div>
        </Card>
      )}

      {mode === "auction" && auction && (
        <div className="space-y-2">
          <p className="text-sm text-[var(--muted)]">{auction.headline}</p>
          {auction.bids.map((b) => (
            <Card key={b.listing_id} className={cn("flex flex-wrap items-center gap-3", b.winner && "border-l-4 border-[var(--success)]")}>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{b.property} — {b.room} {b.winner && <Badge variant="success">winner</Badge>}</p>
                <p className="truncate text-xs text-[var(--muted)]">{b.pitch}</p>
              </div>
              <div className="shrink-0 text-right">
                <p className="text-sm font-semibold">{b.currency} {b.bid.toLocaleString()}<span className="ml-1 text-xs font-normal text-[var(--muted)] line-through">{b.list_price.toLocaleString()}</span></p>
                <p className="text-[0.65rem] text-[var(--muted)]">+ {b.perk}</p>
              </div>
            </Card>
          ))}
          {auction.booking?.status === "confirmed" && (
            <p className="text-sm text-[var(--muted)]">✅ Auto-booked the winner <strong>{auction.booking.currency} {auction.booking.amount?.toLocaleString()}</strong> — firewall-guarded, escrow held, in Finance.</p>
          )}
          {auction.booking?.status === "blocked" && (
            <p className="text-sm text-[var(--warning)]">Winner was sold out — the firewall blocked the auto-book. Pick the next bid or free inventory.</p>
          )}
        </div>
      )}

      {mode === "single" && res && (
        <>
          <Card className={cn("mb-4 border-l-4", res.deal.agreed ? "border-[var(--success)]" : "border-[var(--warning)]")}>
            {res.deal.agreed ? (
              <div>
                <div className="flex flex-wrap items-baseline gap-x-3">
                  <span className="text-sm text-[var(--muted)] line-through">{res.deal.currency} {res.deal.list_price.toLocaleString()}</span>
                  <span className="text-2xl font-bold text-[var(--success)]">{res.deal.currency} {res.deal.price?.toLocaleString()}/night</span>
                  <span className="text-sm font-medium text-[var(--success)]">saved {res.deal.currency} {res.deal.savings.toLocaleString()}</span>
                </div>
                {res.deal.perk && <p className="mt-1 text-sm">+ <strong>{res.deal.perk}</strong></p>}
                {res.booking?.status === "confirmed" && (
                  <p className="mt-2 text-sm text-[var(--muted)]">✅ Auto-booked <strong>{res.booking.currency} {res.booking.amount?.toLocaleString()}</strong> — firewall-guarded, escrow held, posted to Finance, manager notified.</p>
                )}
              </div>
            ) : <p className="text-sm text-[var(--warning)]">No deal — the guest's ceiling was below the room's floor.</p>}
          </Card>

          <div className="space-y-2">
            {res.transcript.map((t, i) => {
              const guest = t.party === "guest_agent";
              return (
                <div key={i} className={cn("flex", guest ? "justify-start" : "justify-end")}>
                  <div className={cn("max-w-[80%] rounded-[var(--r-lg)] px-3 py-2 text-sm", guest ? "bg-[var(--bg)]" : "bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)]")}>
                    <p className="mb-0.5 text-[0.65rem] font-semibold uppercase tracking-wide text-[var(--muted)]">{guest ? "Guest AI" : "Hotel AI"}</p>
                    {t.message}
                    {t.offer != null && <span className="ml-1 rounded-[var(--r-pill)] bg-[var(--surface)] px-1.5 py-0.5 text-xs font-semibold">{res.deal.currency} {t.offer.toLocaleString()}</span>}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------- Listings */

type SupplierListing = { id: string; title: string; price_amount: number | null; price_currency: string; capacity: number | null; perks: string[]; available: boolean };
type SupplierProperty = { id: string; name: string; city: string; kind: string; halal_friendly: boolean; listings: SupplierListing[] };
type Visibility = { cities: string[]; live_rooms: number; appeared_in_searches: number; leads: number };
type Draft = { name: string; city: string; kind: string; room_title: string; description: string; perks: string[]; suggested_price: number; price_currency: string; capacity: number; halal_friendly: boolean };
type Lead = { id: string; status: string; note: string | null; traveler_email: string | null; property_name: string | null; listing_title: string | null };
type PriceRec = { recommended_price: number; currency: string; comp_low: number | null; comp_high: number | null; delta_pct: number; rationale: string; current_price: number | null; sourced: boolean; occupancy_pct?: number | null; demand_level?: string; drivers?: string[] };

const inputCls = "w-full rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-[var(--accent)]";

export function ConsoleListings() {
  const props = useGet<{ properties: SupplierProperty[] }>("/supplier/properties");
  const vis = useGet<Visibility>("/supplier/ai/visibility");
  const leads = useGet<{ leads: Lead[] }>("/supplier/leads");

  const [hint, setHint] = useState({ name: "", city: "", room: "", notes: "", halal_friendly: true });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState("");
  const [prices, setPrices] = useState<Record<string, PriceRec>>({});
  const [replies, setReplies] = useState<Record<string, string>>({});

  const aiDraft = async () => {
    if (!hint.city) return toast.info("Enter a city first.");
    setBusy("draft");
    try {
      const r = await api.post<{ draft: Draft }>("/supplier/ai/draft-listing", { ...hint, kind: "hotel" });
      setDraft(r.draft);
    } catch { toast.error("AI draft failed"); } finally { setBusy(""); }
  };
  const publish = async () => {
    if (!draft) return;
    setBusy("publish");
    try {
      await api.post("/supplier/ai/publish", {
        name: draft.name, city: draft.city, kind: draft.kind, halal_friendly: draft.halal_friendly,
        room_title: draft.room_title, description: draft.description, price_amount: draft.suggested_price,
        price_currency: draft.price_currency, perks: draft.perks, capacity: draft.capacity,
      });
      toast.success("Published — live to travellers searching " + draft.city);
      setDraft(null); setHint({ name: "", city: "", room: "", notes: "", halal_friendly: true });
      props.reload(); vis.reload();
    } catch { toast.error("Publish failed"); } finally { setBusy(""); }
  };
  const aiPrice = async (id: string) => {
    setBusy("price:" + id);
    try {
      const rec = await api.post<PriceRec>(`/supplier/ai/price/${id}`, {});
      setPrices((p) => ({ ...p, [id]: rec }));
    } catch { toast.error("Price agent failed"); } finally { setBusy(""); }
  };
  const aiReply = async (id: string) => {
    setBusy("reply:" + id);
    try { const r = await api.post<{ reply: string }>(`/supplier/ai/lead-reply/${id}`, {}); setReplies((p) => ({ ...p, [id]: r.reply })); }
    catch { toast.error("Concierge failed"); } finally { setBusy(""); }
  };

  const v = vis.data;
  const properties = props.data?.properties ?? [];
  const leadList = leads.data?.leads ?? [];

  return (
    <div>
      <PageHead icon={Building2} title="Listings" subtitle="Your agents write, price and publish rooms — live to travellers, no OTA in the middle." />

      <Card className="mb-4 border-l-4 border-[var(--brand-500)]">
        <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Live to travellers</p>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-6 gap-y-1">
          <span className="text-2xl font-bold text-[var(--brand-500)]">{v?.live_rooms ?? 0} rooms</span>
          <span className="text-sm text-[var(--muted)]">surfaced in <strong className="text-[var(--text)]">{v?.appeared_in_searches ?? 0}</strong> traveller searches · <strong className="text-[var(--text)]">{v?.leads ?? 0}</strong> leads</span>
        </div>
        {!!v?.cities.length && <p className="mt-1 text-sm text-[var(--muted)]">Your direct rooms rank ahead of the OTAs when travellers search: {v.cities.join(", ")}.</p>}
      </Card>

      {/* AI listing composer */}
      <Card className="mb-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 text-[var(--brand-500)]" /> AI listing composer</div>
        <div className="grid gap-2 sm:grid-cols-2">
          <input className={inputCls} placeholder="Property name" value={hint.name} onChange={(e) => setHint({ ...hint, name: e.target.value })} />
          <input className={inputCls} placeholder="City (e.g. Kota Kinabalu)" value={hint.city} onChange={(e) => setHint({ ...hint, city: e.target.value })} />
          <input className={inputCls} placeholder="Room / ticket (e.g. Deluxe Sea View)" value={hint.room} onChange={(e) => setHint({ ...hint, room: e.target.value })} />
          <input className={inputCls} placeholder="Notes (amenities, location…)" value={hint.notes} onChange={(e) => setHint({ ...hint, notes: e.target.value })} />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm"><Switch checked={hint.halal_friendly} onCheckedChange={(c) => setHint({ ...hint, halal_friendly: c })} aria-label="halal" /> Halal-friendly</label>
          <Button onClick={aiDraft} loading={busy === "draft"}><Sparkles className="h-4 w-4" /> Draft with AI</Button>
        </div>

        {draft && (
          <div className="mt-4 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] p-4">
            <div className="mb-1 flex items-center gap-2"><Badge variant="brand">AI draft</Badge><span className="font-semibold">{draft.room_title}</span><span className="ml-auto text-sm font-semibold">{draft.price_currency} {draft.suggested_price.toLocaleString()}/night</span></div>
            <p className="text-sm text-[var(--muted)]">{draft.description}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">{draft.perks.map((p) => <Chip key={p}>{p}</Chip>)}</div>
            <div className="mt-3 flex gap-2"><Button size="sm" onClick={publish} loading={busy === "publish"}>Publish — go live</Button><Button size="sm" variant="ghost" onClick={() => setDraft(null)}>Discard</Button></div>
          </div>
        )}
      </Card>

      {/* Properties + rooms */}
      <h3 className="mb-2 text-sm font-semibold">Your properties</h3>
      {props.loading ? <p className="text-sm text-[var(--muted)]">Loading…</p>
        : !properties.length ? <Card><p className="text-sm text-[var(--muted)]">No properties yet — draft your first room above.</p></Card>
          : properties.map((prop) => (
            <Card key={prop.id} className="mb-3">
              <div className="mb-2 flex items-center gap-2">
                <span className="font-semibold">{prop.name}</span>
                <span className="text-xs text-[var(--muted)]">{prop.city}</span>
                {prop.halal_friendly && <Badge variant="success">halal-friendly</Badge>}
              </div>
              <div className="space-y-2">
                {(prop.listings ?? []).map((l) => (
                  <div key={l.id} className="rounded-[var(--r-md)] bg-[var(--bg)] p-3">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">{l.title}</span>
                      <span className="shrink-0 text-sm font-semibold"><Money amount={l.price_amount ?? 0} currency={l.price_currency} />/night</span>
                      <Button size="sm" variant="secondary" onClick={() => aiPrice(l.id)} loading={busy === "price:" + l.id}><TrendingUp className="h-3.5 w-3.5" /> AI price</Button>
                    </div>
                    {prices[l.id] && (
                      <div className="mt-2 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] p-2 text-sm">
                        <span className="font-semibold text-[var(--brand-500)]">Recommend {prices[l.id].currency} {prices[l.id].recommended_price.toLocaleString()}</span>
                        {prices[l.id].delta_pct ? <span className={cn("ml-2 text-xs", prices[l.id].delta_pct > 0 ? "text-[var(--success)]" : "text-[var(--warning)]")}>{prices[l.id].delta_pct > 0 ? "+" : ""}{prices[l.id].delta_pct}%</span> : null}
                        {prices[l.id].comp_low != null && <span className="ml-2 text-xs text-[var(--muted)]">comp {prices[l.id].currency} {prices[l.id].comp_low}–{prices[l.id].comp_high}</span>}
                        {prices[l.id].occupancy_pct != null && <span className="ml-2 text-xs text-[var(--muted)]">occ {prices[l.id].occupancy_pct}%</span>}
                        {prices[l.id].demand_level && <span className={cn("ml-2 rounded-[var(--r-pill)] px-1.5 py-0.5 text-[0.6rem] font-semibold uppercase", prices[l.id].demand_level === "high" ? "bg-[color-mix(in_srgb,var(--danger,#dc2626)_16%,transparent)] text-[var(--danger,#dc2626)]" : prices[l.id].demand_level === "low" ? "bg-[color-mix(in_srgb,var(--success)_16%,transparent)] text-[var(--success)]" : "bg-[var(--bg)] text-[var(--muted)]")}>{prices[l.id].demand_level} demand</span>}
                        <p className="mt-0.5 text-xs text-[var(--muted)]">{prices[l.id].rationale}{!prices[l.id].sourced ? " (estimate)" : ""}</p>
                        {(prices[l.id].drivers ?? []).length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {prices[l.id].drivers!.map((d) => <span key={d} className="rounded-[var(--r-pill)] bg-[var(--bg)] px-1.5 py-0.5 text-[0.6rem] text-[var(--muted)]">{d}</span>)}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          ))}

      {/* Leads */}
      <h3 className="mb-2 mt-6 text-sm font-semibold">Leads from travellers</h3>
      {!leadList.length ? <Card><p className="text-sm text-[var(--muted)]">No leads yet — they arrive when a traveller books your direct room.</p></Card>
        : leadList.map((ld) => (
          <Card key={ld.id} className="mb-2">
            <div className="flex items-center gap-2">
              <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{ld.listing_title || ld.property_name || "Enquiry"}</p><p className="truncate text-xs text-[var(--muted)]">{ld.traveler_email || "traveller"} · {ld.note || "no note"}</p></div>
              <Badge variant={ld.status === "new" ? "brand" : "success"}>{ld.status}</Badge>
              <Button size="sm" variant="secondary" onClick={() => aiReply(ld.id)} loading={busy === "reply:" + ld.id}><Sparkles className="h-3.5 w-3.5" /> AI reply</Button>
            </div>
            {replies[ld.id] && <p className="mt-2 whitespace-pre-wrap rounded-[var(--r-md)] bg-[var(--bg)] p-3 text-sm">{replies[ld.id]}</p>}
          </Card>
        ))}
    </div>
  );
}
function RiskPill({ level }: { level: string }) {
  const map: Record<string, string> = {
    safe: "bg-[color-mix(in_srgb,var(--success)_18%,transparent)] text-[var(--success)]",
    caution: "bg-[color-mix(in_srgb,var(--warning)_18%,transparent)] text-[var(--warning)]",
    dangerous: "bg-[color-mix(in_srgb,var(--danger,#dc2626)_18%,transparent)] text-[var(--danger,#dc2626)]",
  };
  return <span className={cn("shrink-0 rounded-[var(--r-pill)] px-2 py-0.5 text-[0.65rem] font-medium capitalize", map[level] ?? "bg-[var(--bg)] text-[var(--muted)]")}>{level}</span>;
}
