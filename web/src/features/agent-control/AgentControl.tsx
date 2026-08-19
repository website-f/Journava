import { useEffect, useMemo } from "react";
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
import { Brain, Bot, Activity, GitCompareArrows } from "@/components/ui/icons";

import { cn } from "@/lib/cn";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui";
import { useAgentStream } from "@/hooks/useAgentStream";
import type { AgentStatus } from "@/lib/sse";
import { useIsMobile } from "@/hooks/useMediaQuery";
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
      position: { x: 550, y: 0 },
      data: { label: "Chief", status: "idle" },
      type: "agentNode",
    });
    // Tier 1 — 8 core intelligence agents in row 2
    const tier1 = AGENTS.filter((a) => a.tier === 1);
    tier1.forEach((agent, i) => {
      nodes.push({
        id: agent.slug,
        position: { x: i * 145, y: 110 },
        data: { label: agent.name, status: "idle" },
        type: "agentNode",
      });
    });
    // Tier 2 — 9 enrichment agents in row 3
    const tier2 = AGENTS.filter((a) => a.tier === 2);
    tier2.forEach((agent, i) => {
      nodes.push({
        id: agent.slug,
        position: { x: i * 130, y: 230 },
        data: { label: agent.name, status: "idle" },
        type: "agentNode",
      });
    });
    // Tier 3 — 3 assembly agents in row 4
    const tier3 = AGENTS.filter((a) => a.tier === 3);
    tier3.forEach((agent, i) => {
      nodes.push({
        id: agent.slug,
        position: { x: 380 + i * 170, y: 350 },
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
        markerEnd: { type: MarkerType.ArrowClosed, color: "#94A0B8" },
        style: { stroke: "#94A0B8", strokeWidth: 1.5 },
      })),
    [],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

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
  }, [statusMap, setNodes]);

  const roster = (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {AGENTS.map((agent) => {
        const latest = statusMap[agent.slug];
        const status: AgentStatus = latest?.status ?? "idle";
        return (
          <div key={agent.slug} className="surface-card p-3 flex items-center gap-3">
            <span
              className="h-2.5 w-2.5 rounded-full shrink-0"
              style={{ backgroundColor: STATUS_COLORS[status] }}
            />
            <div className="min-w-0">
              <p className="text-sm font-medium">{agent.name}</p>
              <p className="text-xs text-[var(--muted)] truncate">{latest?.message ?? agent.role}</p>
            </div>
          </div>
        );
      })}
    </div>
  );

  return (
    <div className="mx-auto w-full max-w-6xl">
      <ControlHeader connected={connected} />

      <Tabs defaultValue={isMobile ? "roster" : "topology"}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="topology">
            <GitCompareArrows className="h-4 w-4" /> Topology
          </TabsTrigger>
          <TabsTrigger value="roster">
            <Bot className="h-4 w-4" /> Roster
          </TabsTrigger>
          <TabsTrigger value="live">
            <Activity className="h-4 w-4" /> Live
          </TabsTrigger>
          <TabsTrigger value="brain">
            <Brain className="h-4 w-4" /> Brain
          </TabsTrigger>
        </TabsList>

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

        <TabsContent value="roster">{roster}</TabsContent>

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
        "rounded-[var(--r-md)] border-2 bg-[var(--surface)] px-3 py-2 min-w-[120px] text-center transition-all duration-200",
        isWorking && "animate-pulse",
      )}
      style={{ borderColor: color }}
    >
      <div className="flex items-center justify-center gap-1.5">
        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
        <span className="text-xs font-semibold">{data.label}</span>
      </div>
      {data.message && (
        <p className="mt-0.5 text-[0.6rem] text-[var(--muted)] truncate max-w-[110px]">{data.message}</p>
      )}
    </div>
  );
}

