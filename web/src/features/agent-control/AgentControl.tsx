import { useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  type Node,
  type Edge,
  useNodesState,
  useEdgesState,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { toast } from "sonner";
import { Brain, Activity, GitCompareArrows } from "@/components/ui/icons";

import { cn } from "@/lib/cn";
import { Tabs, TabsList, TabsTrigger, TabsContent, Button } from "@/components/ui";
import { useAgentStream } from "@/hooks/useAgentStream";
import type { AgentStatus } from "@/lib/sse";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { api } from "@/lib/api";
import { BrainGraph } from "./BrainGraph";

/** All 20 agents — the full vision roster (spec section 4). */
const AGENTS = [
  // Chief
  { slug: "chief", name: "Chief", role: "Orchestration & reconciliation", tier: 0 },
  // Tier 1 — core intelligence (8 parallel)
  { slug: "flight", name: "Flight", role: "Atlas skill · search → ticket", tier: 1 },
  { slug: "hotel", name: "Hotel", role: "Compare & auto-switch", tier: 1 },
  { slug: "research", name: "Research", role: "Camofox · YouTube · Reddit", tier: 1 },
  { slug: "weather_risk", name: "Weather", role: "Open-Meteo forecast", tier: 1 },
  { slug: "visa", name: "Visa", role: "Entry requirements · documents", tier: 1 },
  { slug: "emergency", name: "Emergency", role: "Embassy · hospitals · crisis", tier: 1 },
  { slug: "crowd", name: "Crowd", role: "Tourist density · peak seasons", tier: 1 },
  { slug: "risk_advisory", name: "Risk Advisory", role: "GDELT · threat detection", tier: 1 },
  // Tier 2 — enrichment (9 parallel, after critic)
  { slug: "concierge", name: "Concierge", role: "Reservations · events", tier: 2 },
  { slug: "transport", name: "Transport", role: "Ground transit · routes", tier: 2 },
  { slug: "sustainability", name: "Sustainability", role: "Carbon · eco options", tier: 2 },
  { slug: "payment", name: "Payment", role: "Cards · tipping · FX", tier: 2 },
  { slug: "insurance", name: "Insurance", role: "Coverage · risk-based", tier: 2 },
  { slug: "recommendation", name: "Recommendation", role: "Personalized picks", tier: 2 },
  { slug: "analytics", name: "Analytics", role: "Trip optimization", tier: 2 },
  { slug: "language", name: "Language", role: "Phrases · etiquette", tier: 2 },
  { slug: "shopping", name: "Shopping", role: "Markets · souvenirs", tier: 2 },
  // Tier 3 — assembly (3 sequential)
  { slug: "budget", name: "Budget", role: "Cost tracking · FX", tier: 3 },
  { slug: "itinerary", name: "Itinerary", role: "Day-by-day assembly", tier: 3 },
  { slug: "memory", name: "Memory", role: "Gnosion read / write", tier: 3 },
] as const;

const STATUS_COLORS: Record<AgentStatus, string> = {
  idle: "#94A0B8",
  active: "#10B981",
  working: "#4F46E5",
  monitoring: "#3B82F6",
  waiting: "#F59E0B",
  error: "#EF4444",
};

// Graph topology matching supervisor.py 3-tier architecture
const GRAPH_EDGES: Array<[string, string]> = [
  // Chief -> Tier 1 (8 core intelligence)
  ["chief", "flight"],
  ["chief", "hotel"],
  ["chief", "research"],
  ["chief", "weather_risk"],
  ["chief", "visa"],
  ["chief", "emergency"],
  ["chief", "crowd"],
  ["chief", "risk_advisory"],
  // Tier 1 -> Tier 2 (via concierge as gateway)
  ["flight", "concierge"],
  ["hotel", "concierge"],
  ["research", "concierge"],
  ["weather_risk", "concierge"],
  ["visa", "concierge"],
  ["emergency", "concierge"],
  ["crowd", "concierge"],
  ["risk_advisory", "concierge"],
  // Tier 2 fan-out (concierge -> rest of enrichment)
  ["concierge", "transport"],
  ["concierge", "sustainability"],
  ["concierge", "payment"],
  ["concierge", "insurance"],
  ["concierge", "recommendation"],
  ["concierge", "analytics"],
  ["concierge", "language"],
  ["concierge", "shopping"],
  // Tier 2 -> Tier 3 (all enrichment -> budget)
  ["transport", "budget"],
  ["sustainability", "budget"],
  ["payment", "budget"],
  ["insurance", "budget"],
  ["recommendation", "budget"],
  ["analytics", "budget"],
  ["language", "budget"],
  ["shopping", "budget"],
  // Tier 3 sequential
  ["budget", "itinerary"],
  ["itinerary", "memory"],
];

/**
 * Agent Control Center (spec section 3.4) — React Flow graph + event stream.
 * Proves multi-agent collaboration to judges.
 */
export function AgentControl() {
  const { events, statusMap, connected } = useAgentStream();
  const isMobile = useIsMobile();

  // Build initial nodes with positions — 4 rows for 3-tier architecture
  const initialNodes: Node[] = useMemo(() => {
    const nodes: Node[] = [];
    // Chief at top center
    nodes.push({
      id: "chief",
      position: { x: 720, y: 0 },
      data: { label: "Chief", status: "idle" },
      type: "agentNode",
    });
    // Tier 1 — 8 core intelligence agents in row 2
    const tier1 = AGENTS.filter((a) => a.tier === 1);
    tier1.forEach((agent, i) => {
      nodes.push({
        id: agent.slug,
        position: { x: i * 185, y: 140 },
        data: { label: agent.name, status: "idle" },
        type: "agentNode",
      });
    });
    // Tier 2 — 9 enrichment agents in row 3
    const tier2 = AGENTS.filter((a) => a.tier === 2);
    tier2.forEach((agent, i) => {
      nodes.push({
        id: agent.slug,
        position: { x: i * 185, y: 290 },
        data: { label: agent.name, status: "idle" },
        type: "agentNode",
      });
    });
    // Tier 3 — 3 assembly agents in row 4
    const tier3 = AGENTS.filter((a) => a.tier === 3);
    tier3.forEach((agent, i) => {
      nodes.push({
        id: agent.slug,
        position: { x: 560 + i * 220, y: 440 },
        data: { label: agent.name, status: "idle" },
        type: "agentNode",
      });
    });
    return nodes;
  }, []);

  const initialEdges: Edge[] = useMemo(
    () =>
      GRAPH_EDGES.map(([source, target]) => ({
        id: `e-${source}-${target}`,
        source,
        target,
        type: "smoothstep",
        // Animated dashes = data flowing along the graph (the "heartbeat").
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#14b8a6" },
        style: { stroke: "#14b8a6", strokeWidth: 1.6, opacity: 0.5 },
      })),
    [],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Update node styles when status changes
  useEffect(() => {
    setNodes((nds) =>
      nds.map((node) => {
        const latest = statusMap[node.id];
        const status: AgentStatus = latest?.status ?? "idle";
        const color = STATUS_COLORS[status];
        const message = latest?.message ?? AGENTS.find((a) => a.slug === node.id)?.role ?? "";
        return {
          ...node,
          data: { ...node.data, label: AGENTS.find((a) => a.slug === node.id)?.name, status, message },
          style: {
            borderColor: color,
            boxShadow: status === "working" ? `0 0 12px ${color}60` : "none",
          },
        };
      }),
    );

    // Brighten edges on the active path so the "heartbeat" visibly flows through
    // whichever agents are currently working.
    const isHot = (id?: string) => {
      const st = id ? statusMap[id]?.status : undefined;
      return st === "working" || st === "active" || st === "monitoring";
    };
    setEdges((eds) =>
      eds.map((edge) => {
        const hot = isHot(edge.source) || isHot(edge.target);
        return {
          ...edge,
          animated: true,
          style: {
            ...edge.style,
            stroke: hot ? "#0f766e" : "#94A0B8",
            strokeWidth: hot ? 2.4 : 1.4,
            opacity: hot ? 0.95 : 0.45,
          },
        };
      }),
    );
  }, [statusMap, setNodes, setEdges]);

  return (
    <div className="mx-auto w-full max-w-6xl">
      <ControlHeader connected={connected} />

      <Tabs defaultValue="mission">
        <TabsList>
          <TabsTrigger value="mission">
            <Activity className="h-4 w-4" /> Mission Control
          </TabsTrigger>
          <TabsTrigger value="topology">
            <GitCompareArrows className="h-4 w-4" /> Topology
          </TabsTrigger>
          <TabsTrigger value="live">
            <Activity className="h-4 w-4" /> Live
          </TabsTrigger>
          <TabsTrigger value="brain">
            <Brain className="h-4 w-4" /> Brain
          </TabsTrigger>
        </TabsList>

        <TabsContent value="mission">
          <MissionControl events={events} statusMap={statusMap} connected={connected} />
        </TabsContent>

        <TabsContent value="topology">
          <div className="surface-card overflow-hidden" style={{ height: isMobile ? 360 : 480 }}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              nodeTypes={{ agentNode: AgentNodeComponent }}
              fitView
              proOptions={{ hideAttribution: true }}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable={false}
            >
              <Background />
            </ReactFlow>
          </div>
        </TabsContent>

        <TabsContent value="live">
          <EventStream events={events} />
        </TabsContent>

        <TabsContent value="brain">
          <div className="surface-card p-3">
            <BrainGraph />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Sub-components
// --------------------------------------------------------------------------- //

function ControlHeader({ connected }: { connected: boolean }) {
  return (
    <header className="pt-2 pb-6 flex items-start justify-between gap-4 flex-wrap">
      <div>
        <h2 className="font-[family-name:var(--font-display)] text-2xl tracking-tight">Agent Control Center</h2>
        <p className="mt-1 text-sm text-[var(--muted)]">Live agent graph and event stream — proof of multi-agent collaboration.</p>
      </div>
      <span
        className={cn(
          "inline-flex items-center gap-2 rounded-[var(--r-pill)] px-3 py-1.5 text-xs font-medium",
          connected
            ? "bg-[color-mix(in_srgb,var(--success)_16%,transparent)] text-[var(--success)]"
            : "bg-[color-mix(in_srgb,var(--muted)_16%,transparent)] text-[var(--muted)]",
        )}
      >
        <span className={cn("h-2 w-2 rounded-full", connected ? "bg-[var(--success)]" : "bg-[var(--muted)]")} />
        {connected ? "Stream connected" : "Stream offline"}
      </span>
    </header>
  );
}

type StatusMap = Record<string, { status: AgentStatus; message?: string }>;

/** Cinematic live view of the mesh — cores ignite as agents work, with a HUD. */
function MissionControl({ events, statusMap, connected }: {
  events: Array<{ id: string; ts: string; agent: string; message: string }>;
  statusMap: StatusMap;
  connected: boolean;
}) {
  const [launching, setLaunching] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (startedAt == null) return;
    const t = window.setInterval(() => setElapsed(Math.floor((performance.now() - startedAt) / 1000)), 500);
    return () => window.clearInterval(t);
  }, [startedAt]);

  const engaged = AGENTS.filter((a) => { const s = statusMap[a.slug]?.status; return s && s !== "idle"; }).length;
  const done = AGENTS.filter((a) => statusMap[a.slug]?.status === "active").length;

  const launch = async () => {
    setLaunching(true);
    setStartedAt(performance.now());
    setElapsed(0);
    try {
      await api.post("/jobs/plan", { goal: "5-day Bali trip in December, halal food", destination: "Bali", scope: "full_trip" });
      toast.success("Live plan launched — watch the mesh work.");
    } catch {
      toast.error("Couldn't launch the plan.");
    } finally {
      setLaunching(false);
    }
  };

  return (
    <div className="space-y-4">
      <HealthStrip />
      <div className="surface-card flex flex-wrap items-center gap-x-6 gap-y-3 p-4">
        <div className="flex items-center gap-2">
          <span className={cn("h-2.5 w-2.5 rounded-full", connected ? "bg-[var(--success)] animate-pulse" : "bg-[var(--muted)]")} />
          <span className="text-sm font-semibold">{connected ? "Mesh live" : "Idle"}</span>
        </div>
        <Hud label="Agents engaged" value={`${engaged}/${AGENTS.length}`} />
        <Hud label="Completed" value={String(done)} />
        <Hud label="Events" value={String(events.length)} />
        <Hud label="Elapsed" value={`${elapsed}s`} />
        <Button className="ml-auto" onClick={launch} loading={launching}>
          <Activity className="h-4 w-4" /> Launch live plan
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {AGENTS.map((a) => {
          const s = (statusMap[a.slug]?.status ?? "idle") as AgentStatus;
          const busy = s === "working" || s === "monitoring" || s === "waiting";
          const color = STATUS_COLORS[s];
          return (
            <div
              key={a.slug}
              className="surface-card relative overflow-hidden p-3 transition-shadow"
              style={s === "idle" ? undefined : { borderColor: color, borderWidth: 1, boxShadow: `0 0 0 1px ${color}22, 0 4px 16px ${color}22` }}
            >
              {busy && <span className="absolute right-2 top-2 h-2 w-2 animate-ping rounded-full" style={{ background: color }} />}
              <div className="flex items-center gap-2">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-[0.6rem] font-bold text-white" style={{ background: color }}>
                  {a.name.slice(0, 2)}
                </span>
                <span className="truncate text-sm font-medium">{a.name}</span>
              </div>
              <p className="mt-1 truncate text-[0.65rem] text-[var(--muted)]">{statusMap[a.slug]?.message || a.role}</p>
              <p className="mt-1 text-[0.6rem] font-semibold uppercase tracking-wide" style={{ color }}>{s === "active" ? "done" : s}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

type Health = {
  agents: { agent: string; calls: number; errors: number; tokens: number; avg_ms: number; p95_ms: number }[];
  cache: { hits: number; misses: number; hit_rate: number | null };
  totals: { llm_calls_24h: number; errors_24h: number; error_rate: number; tokens_24h: number; slowest_agent: string | null };
};

/** Golden-signal health strip — real ops metrics (LLM calls, error rate, cache
 *  hit-rate, tokens, slowest agent) over the last 24h, refreshed every 15s. */
function HealthStrip() {
  const [h, setH] = useState<Health | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => api.get<Health>("/monitor/health").then((d) => live && setH(d)).catch(() => {});
    load();
    const t = window.setInterval(load, 15000);
    return () => { live = false; window.clearInterval(t); };
  }, []);
  if (!h || !h.totals?.llm_calls_24h) return null;
  const t = h.totals;
  const errPct = Math.round((t.error_rate || 0) * 100);
  const hit = h.cache?.hit_rate != null ? `${Math.round(h.cache.hit_rate * 100)}%` : "—";
  return (
    <div className="surface-card flex flex-wrap items-center gap-x-6 gap-y-3 p-4">
      <span className="text-[0.65rem] font-semibold uppercase tracking-wide text-[var(--muted)]">
        System health · 24h
      </span>
      <Hud label="LLM calls" value={String(t.llm_calls_24h)} />
      <Hud label="Error rate" value={`${errPct}%`} />
      <Hud label="Cache hit" value={hit} />
      <Hud label="Tokens" value={t.tokens_24h.toLocaleString()} />
      {t.slowest_agent && <Hud label="Slowest agent" value={t.slowest_agent} />}
    </div>
  );
}

function Hud({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xl font-bold tabular-nums text-[var(--brand-500)]">{value}</p>
      <p className="text-[0.65rem] text-[var(--muted)]">{label}</p>
    </div>
  );
}

function EventStream({ events }: { events: Array<{ id: string; ts: string; agent: string; message: string }> }) {
  return (
    <aside className="surface-card p-4 min-w-0">
      <h3 className="text-sm font-semibold mb-3">Event stream</h3>
      <ol className="space-y-2 max-h-[22rem] overflow-y-auto font-[family-name:var(--font-mono)] text-[0.7rem] leading-relaxed">
        {events.length === 0 && <li className="text-[var(--muted)]">Waiting for agent activity…</li>}
        {events.map((event) => (
          <li key={event.id} className="min-w-0">
            <span className="text-[var(--muted)]">{new Date(event.ts).toLocaleTimeString()} </span>
            <span className="text-[var(--brand-500)]">{event.agent}</span>{" "}
            <span className="break-words">{event.message}</span>
          </li>
        ))}
      </ol>
    </aside>
  );
}

// Custom React Flow node
function AgentNodeComponent({ data }: { data: { label: string; status: AgentStatus; message?: string } }) {
  const color = STATUS_COLORS[data.status ?? "idle"];
  const isWorking = data.status === "working";

  return (
    <div
      className={cn(
        "rounded-[var(--r-md)] border-2 bg-[var(--surface)] px-3 py-2 w-[158px] text-center transition-all duration-200",
        isWorking && "animate-pulse",
      )}
      style={{ borderColor: color }}
    >
      <div className="flex items-center justify-center gap-1.5">
        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
        <span className="text-xs font-semibold">{data.label}</span>
      </div>
      {data.message && (
        <p className="mt-0.5 truncate text-[0.6rem] text-[var(--muted)]">{data.message}</p>
      )}
    </div>
  );
}

