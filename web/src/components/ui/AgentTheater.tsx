import { useMemo } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/cn";
import type { AgentEvent, AgentStatus } from "@/lib/sse";

/**
 * Live Agent Theater — a cinematic view of the 21-agent mesh working in real
 * time. It reuses the same SSE `events` the loading overlay already receives:
 * the supervisor's 4-phase topology (chief → tier-1 parallel → critic barrier →
 * tier-2 parallel → tier-3 sequential) is drawn as vertical bands, and each
 * node lights up as its agent emits `working` → `active`. No new backend — this
 * is pure visualization over data the graph already streams.
 */

type NodeState = "idle" | "working" | "done" | "error";

type AgentDef = { slug: string; label: string };

// Mirrors api/app/graph/supervisor.py PARALLEL_NODES / ENRICHMENT_NODES /
// SEQUENTIAL_NODES. Kept local (small + stable) so the theater has no cross-
// feature import.
const CHIEF: AgentDef = { slug: "chief", label: "Chief" };
const TIER1: AgentDef[] = [
  { slug: "flight", label: "Flight" },
  { slug: "hotel", label: "Hotel" },
  { slug: "research", label: "Research" },
  { slug: "weather_risk", label: "Weather" },
  { slug: "visa", label: "Visa" },
  { slug: "emergency", label: "Emergency" },
  { slug: "crowd", label: "Crowd" },
  { slug: "risk_advisory", label: "Risk" },
];
const CRITIC: AgentDef = { slug: "critic", label: "Critic" };
const TIER2: AgentDef[] = [
  { slug: "concierge", label: "Concierge" },
  { slug: "transport", label: "Transport" },
  { slug: "sustainability", label: "Eco" },
  { slug: "payment", label: "Payment" },
  { slug: "insurance", label: "Insurance" },
  { slug: "recommendation", label: "Picks" },
  { slug: "analytics", label: "Analytics" },
  { slug: "language", label: "Language" },
  { slug: "shopping", label: "Shopping" },
];
const TIER3: AgentDef[] = [
  { slug: "itinerary", label: "Itinerary" },
  { slug: "budget", label: "Budget" },
  { slug: "memory", label: "Memory" },
];

const WORKING_STATUSES: AgentStatus[] = ["working", "monitoring", "waiting"];

function stateFor(status: AgentStatus | undefined): NodeState {
  if (!status) return "idle";
  if (status === "error") return "error";
  if (status === "active") return "done";
  if (WORKING_STATUSES.includes(status)) return "working";
  return "idle";
}

/* ------------------------------------------------------------------ */

function AgentNode({ def, state }: { def: AgentDef; state: NodeState; critic?: boolean }) {
  const working = state === "working";
  const done = state === "done";
  const error = state === "error";
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      className={cn(
        "relative inline-flex items-center gap-1.5 rounded-[var(--r-pill)] border px-2.5 py-1",
        "text-[0.68rem] font-medium leading-none transition-colors duration-300 select-none",
        error
          ? "border-[var(--danger)]/50 bg-[var(--danger)]/10 text-[var(--danger)]"
          : done
            ? "border-[var(--success)]/50 bg-[var(--success)]/12 text-[var(--success)]"
            : working
              ? "border-[var(--brand-500)]/60 bg-[var(--brand-500)]/12 text-[var(--brand-500)]"
              : "border-[var(--border)] bg-[var(--elevated)] text-[var(--muted)]",
      )}
    >
      {/* status dot with a pulsing halo while working */}
      <span className="relative flex h-2 w-2 shrink-0">
        {working && (
          <motion.span
            className="absolute inline-flex h-full w-full rounded-full bg-[var(--brand-500)]"
            animate={{ scale: [1, 2.4, 1], opacity: [0.7, 0, 0.7] }}
            transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
          />
        )}
        <span
          className={cn(
            "relative inline-flex h-2 w-2 rounded-full",
            error
              ? "bg-[var(--danger)]"
              : done
                ? "bg-[var(--success)]"
                : working
                  ? "bg-[var(--brand-500)]"
                  : "bg-[var(--muted)]/50",
          )}
        />
      </span>
      {def.label}
    </motion.div>
  );
}

/** Vertical connector that "flows" while the tier above is producing data. */
function Connector({ active }: { active: boolean }) {
  return (
    <div className="relative mx-auto my-1 h-4 w-px overflow-hidden bg-[var(--border)]">
      {active && (
        <motion.div
          className="absolute inset-x-0 h-2 bg-[var(--brand-500)]"
          animate={{ y: ["-8px", "16px"] }}
          transition={{ duration: 0.9, repeat: Infinity, ease: "linear" }}
        />
      )}
    </div>
  );
}

function Band({
  title,
  count,
  active,
  children,
}: {
  title: string;
  count?: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="w-full">
      <div className="mb-1.5 flex items-center justify-center gap-2">
        <span
          className={cn(
            "text-[0.6rem] font-semibold uppercase tracking-wider transition-colors",
            active ? "text-[var(--brand-500)]" : "text-[var(--muted)]",
          )}
        >
          {title}
        </span>
        {count && <span className="text-[0.6rem] text-[var(--muted)]">{count}</span>}
      </div>
      <div className="flex flex-wrap items-center justify-center gap-1.5">{children}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

export function AgentTheater({ events }: { events?: AgentEvent[] }) {
  const { statusMap, phase } = useMemo(() => {
    const map: Record<string, AgentStatus> = {};
    let ph = "start";
    // oldest-first so the last event per agent wins
    for (const ev of (events ?? []).slice().reverse()) {
      if (ev.agent === "system") {
        const p = (ev.data as Record<string, unknown> | undefined)?.phase as string | undefined;
        if (p) ph = p;
      } else {
        map[ev.agent] = ev.status;
      }
    }
    return { statusMap: map, phase: ph };
  }, [events]);

  const st = (slug: string) => stateFor(statusMap[slug]);
  const anyIn = (defs: AgentDef[]) =>
    defs.some((d) => st(d.slug) === "working" || st(d.slug) === "done");
  const anyWorking = (defs: AgentDef[]) => defs.some((d) => st(d.slug) === "working");

  const chiefState = st("chief");
  // The critic is a barrier node — it emits phase events, not an agent="critic"
  // status. Infer its state: any Tier-2 node running means the barrier cleared.
  const criticRaw = st("critic");
  const criticState: NodeState =
    criticRaw !== "idle"
      ? criticRaw
      : anyIn(TIER2)
        ? "done"
        : phase === "critic"
          ? "working"
          : "idle";
  const tier1Working = anyWorking(TIER1) || chiefState === "working";
  const tier2Working = anyWorking(TIER2);
  const tier3Working = anyWorking(TIER3);

  return (
    <div className="flex flex-col items-center gap-0 py-1">
      <Band title="Chief" active={chiefState !== "idle"}>
        <AgentNode def={CHIEF} state={chiefState} />
      </Band>

      <Connector active={chiefState === "working" || (chiefState === "done" && !anyIn(TIER1))} />

      <Band title="Core Intelligence" count="8 parallel" active={anyIn(TIER1)}>
        {TIER1.map((d) => (
          <AgentNode key={d.slug} def={d} state={st(d.slug)} />
        ))}
      </Band>

      <Connector active={tier1Working || (anyIn(TIER1) && criticState !== "done")} />

      <Band title="Critic" count="barrier" active={criticState !== "idle"}>
        <AgentNode def={CRITIC} state={criticState} critic />
      </Band>

      <Connector active={criticState === "working" || (criticState === "done" && !anyIn(TIER2))} />

      <Band title="Enrichment" count="9 parallel" active={anyIn(TIER2)}>
        {TIER2.map((d) => (
          <AgentNode key={d.slug} def={d} state={st(d.slug)} />
        ))}
      </Band>

      <Connector active={tier2Working || (anyIn(TIER2) && !anyIn(TIER3))} />

      <Band title="Assembly" count="sequential" active={anyIn(TIER3)}>
        {TIER3.map((d, i) => (
          <div key={d.slug} className="flex items-center gap-1.5">
            <AgentNode def={d} state={st(d.slug)} />
            {i < TIER3.length - 1 && (
              <span className={cn("text-[0.6rem]", tier3Working ? "text-[var(--brand-500)]" : "text-[var(--muted)]")}>
                →
              </span>
            )}
          </div>
        ))}
      </Band>
    </div>
  );
}
