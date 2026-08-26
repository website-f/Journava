import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  TrendingUp, ShieldAlert, Zap, Cloud, AlertTriangle, CheckCircle2, Sparkles, Scales,
} from "@/components/ui/icons";
import type { IconType } from "@/components/ui/icons";
import { Button, Badge, Select } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import { Money } from "@/components/ui/Money";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useGet, PageHead, Section, Card, Stat, Field } from "./ui";

/* ================================================================ Revenue */

type RevSettings = { enabled: boolean; auto_apply: boolean; max_change_pct: number; floor_pct: number };
type RevRoom = { id: string; title: string; property: string; price_amount: number | null; price_currency: string; original_price: number | null };
type Adjustment = { listing_id: string | null; room_title: string | null; old_price: number | null; new_price: number | null; delta_pct: number | null; demand_level: string | null; rationale: string | null; applied: boolean; created_at: string | null };
type RunResult = { applied: boolean; applied_count: number; results: (Adjustment & { currency: string; held: boolean })[] };

const DEMAND_TONE: Record<string, string> = {
  high: "bg-[color-mix(in_srgb,var(--danger)_16%,transparent)] text-[var(--danger)]",
  moderate: "bg-[var(--bg)] text-[var(--muted)]",
  low: "bg-[color-mix(in_srgb,var(--success)_16%,transparent)] text-[var(--success)]",
};

function DeltaPill({ pct }: { pct: number | null }) {
  if (pct == null || pct === 0) return <span className="text-xs text-[var(--muted)]">no change</span>;
  const up = pct > 0;
  return (
    <span className={cn("rounded-[var(--r-pill)] px-2 py-0.5 text-xs font-semibold", up ? "bg-[color-mix(in_srgb,var(--success)_16%,transparent)] text-[var(--success)]" : "bg-[color-mix(in_srgb,var(--warning)_16%,transparent)] text-[var(--warning)]")}>
      {up ? "▲" : "▼"} {Math.abs(pct)}%
    </span>
  );
}

export function ConsoleRevenue() {
  const { data, loading, reload } = useGet<{ settings: RevSettings; rooms: RevRoom[]; recent: Adjustment[] }>("/revenue/autopilot");
  const [cfg, setCfg] = useState<RevSettings | null>(null);
  const [busy, setBusy] = useState("");
  const [run, setRun] = useState<RunResult | null>(null);

  useEffect(() => { if (data?.settings) setCfg(data.settings); }, [data?.settings]);

  const saveCfg = async (patch: Partial<RevSettings>) => {
    const next = { ...(cfg as RevSettings), ...patch };
    setCfg(next);
    try { await api.post("/revenue/autopilot/settings", patch); }
    catch { toast.error("Couldn't save settings"); }
  };
  const doRun = async (apply: boolean) => {
    setBusy(apply ? "apply" : "preview");
    try {
      const r = await api.post<RunResult>("/revenue/autopilot/run", { apply });
      setRun(r);
      const moved = r.results.filter((x) => !x.held).length;
      toast[apply ? "success" : "info"](apply ? `Applied ${r.applied_count} price change(s)` : `Previewed ${moved} suggested change(s)`);
      reload();
    } catch { toast.error("Autopilot run failed"); } finally { setBusy(""); }
  };

  const rooms = data?.rooms ?? [];
  const recent = data?.recent ?? [];

  return (
    <div>
      <PageHead
        icon={TrendingUp}
        title="Revenue autopilot"
        subtitle="A yield agent watches competitor rates + live demand and adjusts your nightly prices — within guardrails you set."
        actions={<>
          <Button size="sm" variant="secondary" onClick={() => void doRun(false)} loading={busy === "preview"}>Preview</Button>
          <Button size="sm" onClick={() => void doRun(true)} loading={busy === "apply"}><Zap className="h-4 w-4" /> Run &amp; apply</Button>
        </>}
      />

      {/* Settings */}
      <Section icon={Sparkles} title="Autopilot settings" subtitle="Guardrails keep price moves safe and gradual." className="mb-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex items-center justify-between gap-3 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5">
            <span><span className="block text-sm font-medium">Autopilot enabled</span><span className="block text-xs text-[var(--muted)]">Include this hotel in the scheduled sweep</span></span>
            <Switch checked={cfg?.enabled ?? false} onCheckedChange={(v) => void saveCfg({ enabled: v })} aria-label="enabled" />
          </label>
          <label className="flex items-center justify-between gap-3 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5">
            <span><span className="block text-sm font-medium">Auto-apply</span><span className="block text-xs text-[var(--muted)]">Write new prices automatically (else just propose)</span></span>
            <Switch checked={cfg?.auto_apply ?? false} onCheckedChange={(v) => void saveCfg({ auto_apply: v })} aria-label="auto-apply" />
          </label>
          <Field label="Max change per run">
            <Select value={String(cfg?.max_change_pct ?? 15)} onValueChange={(v) => void saveCfg({ max_change_pct: Number(v) })}
              options={[5, 10, 15, 20, 25].map((n) => ({ value: String(n), label: `± ${n}%` }))} aria-label="max change" />
          </Field>
          <Field label="Price floor (% of list price)">
            <Select value={String(cfg?.floor_pct ?? 60)} onValueChange={(v) => void saveCfg({ floor_pct: Number(v) })}
              options={[40, 50, 60, 70, 80].map((n) => ({ value: String(n), label: `${n}%` }))} aria-label="floor" />
          </Field>
        </div>
      </Section>

      {/* Run results */}
      {run && (
        <Section
          icon={Zap}
          title={run.applied ? "Applied this run" : "Preview — proposed changes"}
          subtitle={run.applied ? `${run.applied_count} price(s) updated` : "Nothing changed yet — press Run & apply to commit"}
          tone={run.applied ? "success" : "brand"}
          className="mb-4"
          bodyClassName="space-y-2"
        >
          {run.results.length === 0 && <p className="text-sm text-[var(--muted)]">No priced rooms to adjust yet.</p>}
          {run.results.map((r) => (
            <div key={r.listing_id} className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold">{r.room_title}</span>
                {r.demand_level && <span className={cn("rounded-[var(--r-pill)] px-2 py-0.5 text-[0.6rem] font-semibold uppercase", DEMAND_TONE[r.demand_level] ?? DEMAND_TONE.moderate)}>{r.demand_level} demand</span>}
                <span className="ml-auto flex items-center gap-2 text-sm">
                  <span className="text-[var(--muted)] line-through"><Money amount={r.old_price ?? 0} currency={r.currency} /></span>
                  <span className="font-semibold"><Money amount={r.new_price ?? 0} currency={r.currency} /></span>
                  <DeltaPill pct={r.delta_pct} />
                  {r.held ? <Badge>held</Badge> : r.applied ? <Badge variant="success">applied</Badge> : <Badge variant="brand">proposed</Badge>}
                </span>
              </div>
              {r.rationale && <p className="mt-1 text-xs text-[var(--muted)]">{r.rationale}</p>}
            </div>
          ))}
        </Section>
      )}

      {/* Current rooms */}
      <Section icon={TrendingUp} title="Your priced rooms" subtitle={`${rooms.length} room(s)`} className="mb-4" bodyClassName="space-y-2">
        {loading ? <p className="text-sm text-[var(--muted)]">Loading…</p>
          : !rooms.length ? <p className="text-sm text-[var(--muted)]">No rooms yet — add one under Listings.</p>
            : rooms.map((r) => (
              <div key={r.id} className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate font-medium">{r.title}</span>
                <span className="truncate text-xs text-[var(--muted)]">{r.property}</span>
                <span className="font-semibold"><Money amount={r.price_amount ?? 0} currency={r.price_currency} /><span className="text-xs font-normal text-[var(--muted)]">/night</span></span>
              </div>
            ))}
      </Section>

      {/* Audit log */}
      {!!recent.length && (
        <Section icon={CheckCircle2} title="Recent adjustments" subtitle="Every move the autopilot made — proposed or applied." bodyClassName="space-y-1.5">
          {recent.map((a, i) => (
            <div key={i} className="flex items-center gap-2 text-sm">
              <span className="min-w-0 flex-1 truncate">{a.room_title}</span>
              <DeltaPill pct={a.delta_pct} />
              {a.applied ? <Badge variant="success">applied</Badge> : <Badge>proposed</Badge>}
              <span className="w-24 shrink-0 text-right text-[0.65rem] text-[var(--muted)]">{(a.created_at || "").slice(0, 10)}</span>
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}

/* ================================================================ War Room */

type Scenario = { id: string; label: string; icon: string };
type Option = { name: string; description: string; projected_outcome: string; effort: string };
type WarResult = {
  error?: string; situation: string; scenario_label?: string;
  impact: { revenue_at_risk_pct: number; summary: string };
  options: Option[]; red_team: string; our_counter: string; recommended: string;
  stats?: { live_rooms: number; avg_nightly_rate: number | null; currency: string; bookings: number; booked_revenue: number };
};

const SCENARIO_ICON: Record<string, IconType> = { trend: TrendingUp, shield: ShieldAlert, cloud: Cloud, zap: Zap, alert: AlertTriangle };
const EFFORT_TONE: Record<string, "success" | "warning" | "default"> = { low: "success", medium: "default", high: "warning" };

export function ConsoleWarRoom() {
  const { data } = useGet<{ scenarios: Scenario[] }>("/wargame/scenarios");
  const [picked, setPicked] = useState<string | null>(null);
  const [custom, setCustom] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<WarResult | null>(null);

  const scenarios = data?.scenarios ?? [];

  const run = async () => {
    if (!picked && !custom.trim()) return toast.info("Pick a scenario or describe one.");
    setBusy(true);
    try {
      const r = await api.post<WarResult>("/wargame/run", { scenario_id: picked, custom: custom.trim() || undefined });
      if (r.error) { toast.info(r.error); return; }
      setRes(r);
    } catch { toast.error("War-game failed"); } finally { setBusy(false); }
  };

  const cur = res?.stats?.currency ?? "MYR";
  return (
    <div>
      <PageHead
        icon={Scales}
        title="War room"
        subtitle="Game out a business shock against your real numbers — an AI strategist returns the impact, your best moves, and the likely counter-move."
      />

      <Section icon={AlertTriangle} title="Pick a disruption" subtitle="Choose a scenario or describe your own." className="mb-4">
        <div className="flex flex-wrap gap-2">
          {scenarios.map((s) => {
            const Icon = SCENARIO_ICON[s.icon] ?? AlertTriangle;
            const active = picked === s.id;
            return (
              <button
                key={s.id}
                onClick={() => { setPicked(active ? null : s.id); }}
                className={cn(
                  "flex items-center gap-2 rounded-[var(--r-pill)] border px-3 py-2 text-sm font-medium transition-colors",
                  active ? "border-transparent bg-[var(--brand-500)] text-white" : "border-[var(--border)] bg-[var(--bg)] text-[var(--text)] hover:border-[var(--brand-400)]",
                )}
              >
                <Icon className="h-4 w-4" weight="duotone" /> {s.label}
              </button>
            );
          })}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            className="min-w-0 flex-1 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-400)]"
            placeholder="…or describe your own scenario"
            value={custom}
            onChange={(e) => { setCustom(e.target.value); if (e.target.value) setPicked(null); }}
          />
          <Button onClick={run} loading={busy}><Sparkles className="h-4 w-4" /> War-game it</Button>
        </div>
      </Section>

      {res && (
        <div className="space-y-4">
          <Section icon={AlertTriangle} title={res.scenario_label || "Scenario"} tone="brand">
            <p className="text-sm">{res.situation}</p>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Revenue at risk" value={`${res.impact?.revenue_at_risk_pct ?? 0}%`} tone="warning" />
              <Stat label="Live rooms" value={res.stats?.live_rooms ?? 0} />
              <Stat label="Avg rate" value={<Money amount={res.stats?.avg_nightly_rate ?? 0} currency={cur} />} />
              <Stat label="Booked revenue" value={<Money amount={res.stats?.booked_revenue ?? 0} currency={cur} />} />
            </div>
            {res.impact?.summary && <p className="mt-3 text-sm text-[var(--muted)]">{res.impact.summary}</p>}
          </Section>

          <Section icon={Sparkles} title="Response options" subtitle="Ranked — best first." bodyClassName="grid gap-3 sm:grid-cols-3">
            {res.options.map((o, i) => (
              <div key={i} className="flex flex-col rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] p-3">
                <div className="flex items-center gap-2">
                  <span className="grid h-6 w-6 place-items-center rounded-full bg-[var(--brand-500)] text-xs font-bold text-white">{i + 1}</span>
                  <span className="min-w-0 flex-1 text-sm font-semibold">{o.name}</span>
                  <Badge variant={EFFORT_TONE[o.effort] ?? "default"}>{o.effort}</Badge>
                </div>
                <p className="mt-2 text-xs text-[var(--muted)]">{o.description}</p>
                <p className="mt-2 text-xs"><span className="font-semibold text-[var(--success)]">Outcome:</span> {o.projected_outcome}</p>
              </div>
            ))}
          </Section>

          <div className="grid gap-4 lg:grid-cols-2">
            <Section icon={ShieldAlert} title="Their counter-move" tone="brand">
              <p className="text-sm text-[var(--muted)]">{res.red_team || "—"}</p>
            </Section>
            <Section icon={CheckCircle2} title="Our counter" tone="success">
              <p className="text-sm text-[var(--muted)]">{res.our_counter || "—"}</p>
            </Section>
          </div>

          <Card className="border-l-4 border-[var(--brand-500)]">
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold"><Sparkles className="h-4 w-4 text-[var(--brand-500)]" /> Recommended play</div>
            <p className="text-sm">{res.recommended}</p>
          </Card>
        </div>
      )}
    </div>
  );
}
