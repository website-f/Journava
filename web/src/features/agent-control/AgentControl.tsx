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
import { Brain } from "lucide-react";

import { cn } from "@/lib/cn";
import { useAgentStream } from "@/hooks/useAgentStream";
import type { AgentStatus } from "@/lib/sse";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { BrainGraph } from "./BrainGraph";

/** The 8 agents shipped for the MVP (spec section 4). */
const AGENTS = [
  { slug: "chief", name: "Chief", role: "Orchestration & reconciliation" },
  { slug: "flight", name: "Flight", role: "Atlas skill · search → ticket" },
  { slug: "hotel", name: "Hotel", role: "Compare & auto-switch" },
  { slug: "research", name: "Research", role: "Camofox · YouTube · Reddit" },
  { slug: "weather_risk", name: "Weather / Risk", role: "Open-Meteo · GDELT" },
  { slug: "budget", name: "Budget", role: "Cost tracking · FX" },
  { slug: "itinerary", name: "Itinerary", role: "Day-by-day assembly" },
  { slug: "memory", name: "Memory", role: "Gnosion read / write" },
] as const;

const STATUS_COLORS: Record<AgentStatus, string> = {
  idle: "#94A0B8",
  active: "#10B981",
  working: "#4F46E5",
  monitoring: "#3B82F6",
  waiting: "#F59E0B",
  error: "#EF4444",
};

// Graph topology matching supervisor.py
const GRAPH_EDGES: Array<[string, string]> = [
  ["chief", "flight"],
  ["chief", "hotel"],
  ["chief", "research"],
  ["chief", "weather_risk"],
  ["flight", "budget"],
  ["hotel", "budget"],
  ["research", "budget"],
  ["weather_risk", "budget"],
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

  // Build initial nodes with positions
  const initialNodes: Node[] = useMemo(() => {
    const nodes: Node[] = [];
    // Chief at top center
    nodes.push({
      id: "chief",
      position: { x: 300, y: 0 },
      data: { label: "Chief", status: "idle" },
      type: "agentNode",
    });
    // Specialists in middle row
    const specialists = ["flight", "hotel", "research", "weather_risk"];
    specialists.forEach((slug, i) => {
      const meta = AGENTS.find((a) => a.slug === slug)!;
      nodes.push({
        id: slug,
        position: { x: i * 180, y: 120 },
        data: { label: meta.name, status: "idle" },
        type: "agentNode",
      });
    });
    // Sequential at bottom
    const sequential = ["budget", "itinerary", "memory"];
    sequential.forEach((slug, i) => {
      const meta = AGENTS.find((a) => a.slug === slug)!;
      nodes.push({
        id: slug,
        position: { x: 180 + i * 180, y: 240 },
        data: { label: meta.name, status: "idle" },
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

  if (isMobile) {
    // Simplified list view on mobile
    return (
      <div className="mx-auto w-full max-w-lg">
        <ControlHeader connected={connected} />
        <div className="space-y-2 mb-6">
          {AGENTS.map((agent) => {
            const latest = statusMap[agent.slug];
            const status: AgentStatus = latest?.status ?? "idle";
            return (
              <div key={agent.slug} className="surface-card p-3 flex items-center gap-3">
                <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: STATUS_COLORS[status] }} />
                <div className="min-w-0">
                  <p className="text-sm font-medium">{agent.name}</p>
                  <p className="text-xs text-[var(--muted)] truncate">{latest?.message ?? agent.role}</p>
                </div>
              </div>
            );
          })}
        </div>
        <EventStream events={events} />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl">
      <ControlHeader connected={connected} />

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        {/* React Flow graph + Brain Graph */}
        <div className="space-y-4">
          {/* Agent Topology */}
          <div className="surface-card overflow-hidden" style={{ height: 380 }}>
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

          {/* Brain Graph — collapsible panel */}
          <BrainGraphPanel />
        </div>

        {/* Event stream */}
        <EventStream events={events} />
      </div>
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

/** Collapsible Brain Graph panel below the agent topology. */
function BrainGraphPanel() {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--surface)] overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "w-full flex items-center justify-between px-4 py-3 text-sm font-medium transition-colors",
          "hover:bg-[color-mix(in_srgb,var(--brand-400)_6%,transparent)]",
        )}
      >
        <span className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-[var(--brand-500)]" />
          Brain — Knowledge Graph
        </span>
        <span className="text-xs text-[var(--muted)]">
          {open ? "Hide" : "Show"}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-3">
          <BrainGraph />
        </div>
      )}
    </div>
  );
}
