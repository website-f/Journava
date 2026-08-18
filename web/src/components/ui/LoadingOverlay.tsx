import { useEffect, useMemo, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X, Clock, CheckCircle2, Circle, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { useScrollLock } from "@/hooks/useScrollLock";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { AgentPulse } from "./AgentPulse";
import type { AgentEvent } from "@/lib/sse";

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

type OverlayProps = {
  open: boolean;
  /** All accumulated SSE events (newest first from useAgentStream). */
  events?: AgentEvent[];
  /** Called when the user clicks Cancel or confirms navigation. */
  onCancel?: () => void;
};

/* Phase metadata emitted by the supervisor in SSE data payloads. */
const PHASE_ORDER = ["start", "tier1", "critic", "tier2", "tier3", "done"] as const;
const PHASE_LABEL: Record<string, string> = {
  start: "Initializing",
  tier1: "Core Intelligence",
  critic: "Critic Review",
  tier2: "Enrichment",
  tier3: "Assembly",
  done: "Complete",
};

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

function fmtTime(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = Math.round(secs % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function statusIcon(status: string) {
  switch (status) {
    case "working":
      return <Loader2 className="h-3 w-3 animate-spin text-[var(--brand-400)]" />;
    case "active":
      return <CheckCircle2 className="h-3 w-3 text-[var(--success)]" />;
    case "error":
      return <Circle className="h-3 w-3 text-[var(--danger)] fill-[var(--danger)]" />;
    default:
      return <Circle className="h-3 w-3 text-[var(--muted)]" />;
  }
}

function agentLabel(slug: string): string {
  return slug
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

/**
 * Full-screen loading overlay with a live agent log, progress phases,
 * ETA countdown, cancel button, and browser-refresh protection.
 *
 * Replaces the old static "Journava is working…" card.
 */
export function LoadingOverlay({ open, events, onCancel }: OverlayProps) {
  useScrollLock(open);
  const trapRef = useFocusTrap<HTMLDivElement>(open);
  const logRef = useRef<HTMLDivElement>(null);

  /* ----- Block refresh / navigation while agents are running ----- */
  useEffect(() => {
    if (!open) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "Agents are still working. Leave anyway?";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [open]);

  /* ----- Auto-scroll the log panel to newest entry ----- */
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events?.length]);

  /* ----- Derive progress state from events ----- */
  const { logEntries, currentPhase, phaseIndex, agentsDone, eta, elapsed } = useMemo(() => {
    const sorted = (events ?? []).slice().reverse(); // oldest first for display

    const logs = sorted.map((ev) => ({
      id: ev.id,
      agent: ev.agent,
      status: ev.status,
      message: ev.message,
      phase: (ev.data as Record<string, unknown> | undefined)?.phase as string | undefined,
      eta: (ev.data as Record<string, unknown> | undefined)?.eta_s as number | undefined,
      elapsed: (ev.data as Record<string, unknown> | undefined)?.elapsed_s as number | undefined,
    }));

    // Find current phase from system events
    let phase = "start";
    let pIdx = 0;
    let etaS = 98;
    let elapsedS = 0;
    for (const entry of logs) {
      if (entry.agent === "system" && entry.phase) {
        phase = entry.phase;
        pIdx = PHASE_ORDER.indexOf(entry.phase as typeof PHASE_ORDER[number]);
        if (pIdx < 0) pIdx = 0;
        if (typeof entry.eta === "number") etaS = entry.eta;
        if (typeof entry.elapsed === "number") elapsedS = entry.elapsed;
      }
    }

    // Count unique agents that have emitted "active" (done)
    const doneSet = new Set<string>();
    for (const ev of sorted) {
      if (ev.status === "active" && ev.agent !== "system") doneSet.add(ev.agent);
    }

    return {
      logEntries: logs,
      currentPhase: PHASE_LABEL[phase] ?? phase,
      phaseIndex: pIdx,
      agentsDone: doneSet.size,
      eta: etaS,
      elapsed: elapsedS,
    };
  }, [events]);

  const progressPct = Math.min(100, ((phaseIndex + 1) / PHASE_ORDER.length) * 100);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          role="dialog"
          aria-modal="true"
          aria-live="assertive"
          className={cn(
            "fixed inset-0 z-[80] grid place-items-center",
            "bg-black/50 backdrop-blur-md p-4",
          )}
        >
          <motion.div
            ref={trapRef}
            tabIndex={-1}
            initial={{ y: 16, scale: 0.97, opacity: 0 }}
            animate={{ y: 0, scale: 1, opacity: 1 }}
            exit={{ y: 16, scale: 0.97, opacity: 0 }}
            transition={{ type: "spring", damping: 26, stiffness: 220 }}
            className={cn(
              "w-full max-w-lg rounded-[var(--r-lg)] bg-[var(--elevated)]",
              "border border-[var(--border)] shadow-[var(--shadow-2)]",
              "outline-none flex flex-col overflow-hidden",
            )}
          >
            {/* ── Header ── */}
            <div className="flex items-start justify-between px-5 pt-5 pb-3">
              <div className="flex items-center gap-3">
                <AgentPulse className="h-8 w-8 shrink-0" />
                <div>
                  <h3 className="font-[family-name:var(--font-display)] text-base leading-tight">
                    Journava is working…
                  </h3>
                  <p className="text-xs text-[var(--muted)] mt-0.5">
                    {currentPhase} · {agentsDone} agent{agentsDone !== 1 ? "s" : ""} done
                  </p>
                </div>
              </div>
              {onCancel && (
                <button
                  onClick={onCancel}
                  className={cn(
                    "flex items-center gap-1.5 rounded-[var(--r-pill)] px-3 py-1.5",
                    "text-xs font-medium transition-colors",
                    "bg-[var(--danger)]/10 text-[var(--danger)]",
                    "hover:bg-[var(--danger)]/20",
                  )}
                >
                  <X className="h-3.5 w-3.5" />
                  Cancel
                </button>
              )}
            </div>

            {/* ── Progress bar ── */}
            <div className="px-5 pb-2">
              <div className="h-1.5 rounded-full bg-[var(--border)] overflow-hidden">
                <motion.div
                  className="h-full rounded-full bg-[var(--brand-500)]"
                  initial={{ width: 0 }}
                  animate={{ width: `${progressPct}%` }}
                  transition={{ duration: 0.6, ease: "easeOut" }}
                />
              </div>
              <div className="mt-1.5 flex justify-between text-[0.6rem] text-[var(--muted)]">
                <span>{currentPhase}</span>
                <span className="flex items-center gap-1">
                  <Clock className="h-2.5 w-2.5" />
                  {eta > 0 ? `~${fmtTime(eta)} remaining` : fmtTime(elapsed)}
                </span>
              </div>
            </div>

            {/* ── Phase pills ── */}
            <div className="px-5 pb-2 flex gap-1 flex-wrap">
              {PHASE_ORDER.filter((p) => p !== "start" && p !== "done").map((phase, i) => {
                const active = i <= phaseIndex - 1; // phaseIndex is 0-based, "start" is index 0
                const current = i === phaseIndex - 1;
                return (
                  <span
                    key={phase}
                    className={cn(
                      "inline-flex items-center rounded-[var(--r-pill)] px-2 py-0.5",
                      "text-[0.6rem] font-medium transition-colors duration-300",
                      current
                        ? "bg-[var(--brand-500)]/15 text-[var(--brand-500)] ring-1 ring-[var(--brand-500)]/30"
                        : active
                          ? "bg-[var(--success)]/10 text-[var(--success)]"
                          : "bg-[var(--border)]/40 text-[var(--muted)]",
                    )}
                  >
                    {active && !current && <CheckCircle2 className="h-2.5 w-2.5 mr-0.5" />}
                    {PHASE_LABEL[phase]}
                  </span>
                );
              })}
            </div>

            {/* ── Live log panel ── */}
            <div
              ref={logRef}
              className={cn(
                "mx-4 mb-4 max-h-52 overflow-y-auto rounded-[var(--r-md)]",
                "bg-[color-mix(in_srgb,var(--bg)_80%,black)] border border-[var(--border)]",
                "px-3 py-2 scroll-smooth",
              )}
            >
              {logEntries.length === 0 && (
                <p className="text-xs text-[var(--muted)] py-2 text-center">
                  Waiting for agents to start…
                </p>
              )}
              {logEntries.map((entry) => (
                <motion.div
                  key={entry.id}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.2 }}
                  className="flex items-start gap-2 py-[3px] text-[0.7rem] leading-snug"
                >
                  <span className="shrink-0 mt-[2px]">{statusIcon(entry.status)}</span>
                  <span className="text-[var(--muted)] shrink-0 font-mono text-[0.6rem] tabular-nums w-12">
                    {new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                  </span>
                  {entry.agent !== "system" && (
                    <span className="shrink-0 font-medium text-[var(--brand-400)]">
                      {agentLabel(entry.agent)}
                    </span>
                  )}
                  <span
                    className={cn(
                      "min-w-0",
                      entry.status === "error"
                        ? "text-[var(--danger)]"
                        : entry.agent === "system"
                          ? "text-[var(--brand-400)] font-medium"
                          : "text-[var(--text)]",
                    )}
                  >
                    {entry.message}
                  </span>
                </motion.div>
              ))}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
