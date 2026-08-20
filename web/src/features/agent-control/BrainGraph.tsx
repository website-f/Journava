import { useEffect, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  useNodesState,
  useEdgesState,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api } from "@/lib/api";

interface BrainGraphNode {
  id: string;
  label: string;
  domain: string;
  weight: number;
}
interface BrainGraphEdge {
  source: string;
  target: string;
  strength: number;
}
interface BrainGraphData {
  nodes: BrainGraphNode[];
  edges: BrainGraphEdge[];
}

const DOMAIN_COLORS: Record<string, string> = {
  traveler_profile: "#0F766E",
  flights: "#2563EB",
  hotels: "#16A34A",
  destinations: "#E0973B",
  weather: "#0891B2",
  budgets: "#DC2626",
  itinerary: "#DB2777",
  outcomes: "#7C3AED",
};

const NODE_W = 150;
const NODE_H = 46;

const DEMO: BrainGraphData = {
  nodes: [
    { id: "traveler_profile", label: "Traveler Profile", domain: "traveler_profile", weight: 3 },
    { id: "flights", label: "Flights", domain: "flights", weight: 5 },
    { id: "hotels", label: "Hotels", domain: "hotels", weight: 4 },
    { id: "destinations", label: "Destinations", domain: "destinations", weight: 6 },
    { id: "weather", label: "Weather", domain: "weather", weight: 2 },
    { id: "budgets", label: "Budgets", domain: "budgets", weight: 3 },
    { id: "itinerary", label: "Itinerary", domain: "itinerary", weight: 4 },
    { id: "outcomes", label: "Outcomes", domain: "outcomes", weight: 2 },
  ],
  edges: [
    { source: "traveler_profile", target: "flights", strength: 0.8 },
    { source: "traveler_profile", target: "hotels", strength: 0.7 },
    { source: "traveler_profile", target: "destinations", strength: 0.9 },
    { source: "flights", target: "budgets", strength: 0.6 },
    { source: "hotels", target: "budgets", strength: 0.6 },
    { source: "destinations", target: "itinerary", strength: 0.8 },
    { source: "weather", target: "itinerary", strength: 0.5 },
    { source: "outcomes", target: "flights", strength: 0.4 },
    { source: "budgets", target: "itinerary", strength: 0.5 },
  ],
};

/** Even circular placement, radius scaled so nodes never overlap. */
function circle(index: number, total: number): { x: number; y: number } {
  const radius = Math.max(170, total * 30);
  const angle = (2 * Math.PI * index) / Math.max(1, total) - Math.PI / 2;
  return {
    x: Math.cos(angle) * radius - NODE_W / 2,
    y: Math.sin(angle) * radius - NODE_H / 2,
  };
}

/**
 * Gnosion knowledge-graph view — pan/zoom/drag React Flow. Unlike the Topology
 * tab (whose animated edges show data *flowing* between working agents), the
 * Brain just shows which memory domains are *connected*, so its edges are static
 * dashed links. All nodes render at once; a mount key re-fits the view once the
 * async data has loaded (the previous version fit an empty graph → only one node
 * was visible).
 */
export function BrainGraph() {
  const [data, setData] = useState<BrainGraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    api
      .get<BrainGraphData>("/brain/graph")
      .then((d) => setData(d?.nodes?.length ? d : DEMO))
      .catch(() => setData(DEMO))
      .finally(() => setLoading(false));
  }, []);

  const totalMemories = useMemo(
    () => data?.nodes.reduce((sum, n) => sum + n.weight, 0) ?? 0,
    [data],
  );

  useEffect(() => {
    if (!data) return;
    const ids = new Set(data.nodes.map((n) => n.id));

    setNodes(
      data.nodes.map((n, i) => {
        const color = DOMAIN_COLORS[n.domain] ?? "#6B7280";
        return {
          id: n.id,
          position: circle(i, data.nodes.length),
          data: { label: `${n.label}\n${n.weight} memories` },
          style: {
            width: NODE_W,
            height: NODE_H,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
            whiteSpace: "pre-line",
            lineHeight: 1.15,
            fontSize: 11,
            fontWeight: 600,
            color: "var(--text)",
            background: `color-mix(in srgb, ${color} 16%, var(--surface))`,
            border: `1.5px solid ${color}`,
            borderRadius: 12,
            boxShadow: `0 0 10px ${color}25`,
          },
        } satisfies Node;
      }),
    );

    setEdges(
      data.edges
        .filter((e) => ids.has(e.source) && ids.has(e.target))
        .map((e, i) => ({
          id: `be-${i}`,
          source: e.source,
          target: e.target,
          animated: false, // static connections — flow lives in the Topology tab
          style: {
            stroke: "#94A0B8",
            strokeWidth: 1 + e.strength * 1.6,
            opacity: 0.55,
            strokeDasharray: "4 4",
          },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#94A0B8" },
        })),
    );
  }, [data, setNodes, setEdges]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-[var(--muted)]">
        Loading brain graph…
      </div>
    );
  }

  return (
    <div className="relative">
      <div className="absolute right-3 top-2 z-10 flex items-center gap-2 rounded-[var(--r-pill)] glass px-2.5 py-1">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--brand-400)] opacity-75" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[var(--brand-500)]" />
        </span>
        <span className="text-[0.65rem] font-medium text-[var(--muted)]">
          {totalMemories} memories · {data?.nodes.length ?? 0} domains
        </span>
      </div>

      <div className="h-[26rem] overflow-hidden rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--surface)]">
        <ReactFlow
          // Remount once the async nodes land so fitView frames them (fitting an
          // empty graph on first mount is what left only one node visible).
          key={nodes.length}
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          fitView
          fitViewOptions={{ padding: 0.28 }}
          minZoom={0.3}
          maxZoom={1.8}
          proOptions={{ hideAttribution: true }}
          nodesConnectable={false}
          elementsSelectable={false}
        >
          <Background gap={16} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
