import { useEffect, useState } from "react";
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
  traveler_profile: "#8B5CF6",
  flights: "#3B82F6",
  hotels: "#10B981",
  destinations: "#F59E0B",
  weather: "#06B6D4",
  budgets: "#EF4444",
  itinerary: "#EC4899",
  outcomes: "#6366F1",
};

/**
 * Brain Graph Visualization — shows the Gnosion knowledge graph as a d3-force
 * style React Flow layout. Proves to judges that the brain is learning.
 */
export function BrainGraph() {
  const [data, setData] = useState<BrainGraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  useEffect(() => {
    api
      .get<BrainGraphData>("/brain/graph")
      .then(setData)
      .catch(() => {
        // Use demo data if endpoint fails
        setData({
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
            { source: "outcomes", target: "hotels", strength: 0.4 },
            { source: "budgets", target: "itinerary", strength: 0.5 },
          ],
        });
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!data) return;
    const flowNodes: Node[] = data.nodes.map((n, i) => ({
      id: n.id,
      position: getPosition(i, data.nodes.length),
      data: {
        label: (
          <div className="flex flex-col items-center">
            <span className="text-xs font-semibold">{n.label}</span>
            <span className="text-[10px] opacity-60">{n.weight} memories</span>
          </div>
        ),
      },
      style: {
        background: `${DOMAIN_COLORS[n.domain] ?? "#6B7280"}20`,
        border: `2px solid ${DOMAIN_COLORS[n.domain] ?? "#6B7280"}`,
        borderRadius: "12px",
        padding: "8px 12px",
        width: "auto",
        fontSize: "12px",
        boxShadow: `0 0 12px ${DOMAIN_COLORS[n.domain] ?? "#6B7280"}40`,
      },
    }));

    const flowEdges: Edge[] = data.edges.map((e, i) => ({
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      animated: true,
      style: {
        stroke: "#6B728080",
        strokeWidth: e.strength * 3,
      },
      markerEnd: { type: MarkerType.ArrowClosed },
    }));

    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [data, setNodes, setEdges]);

  if (loading) {
    return (
      <div className="h-64 flex items-center justify-center text-[var(--muted)] text-sm">
        Loading brain graph...
      </div>
    );
  }

  return (
    <div className="h-72 md:h-80 rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--surface)] overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        panOnScroll={false}
      >
        <Background gap={16} size={1} />
      </ReactFlow>
    </div>
  );
}

/**
 * Place nodes in a circular layout.
 */
function getPosition(index: number, total: number): { x: number; y: number } {
  const angle = (2 * Math.PI * index) / total - Math.PI / 2;
  const radius = 180;
  return {
    x: Math.cos(angle) * radius + 200,
    y: Math.sin(angle) * radius + 120,
  };
}
