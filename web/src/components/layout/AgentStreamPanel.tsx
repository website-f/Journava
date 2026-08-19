import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, ChevronDown, GripHorizontal, X } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { useAgentStream } from "@/hooks/useAgentStream";
import type { AgentEvent } from "@/lib/sse";

/**
 * The persistent agent activity surface from §10.7.
 *
 * Desktop (≥lg): a collapsible right-hand column beside the main content.
 * Mobile (<md):  a swipe-up drawer over it.
 *
 * Both render the same event list from the shared stream, so the "agents are
 * working" signal is present on every page rather than only in the Agent
 * Control Center.
 */

const STATUS_COLOR: Record<string, string> = {
  idle: "var(--muted)",
  active: "var(--success)",
  working: "var(--brand-500)",
  monitoring: "var(--info)",
  waiting: "var(--warning)",
  error: "var(--danger)",
};

function EventList({ events }: { events: AgentEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="px-1 py-6 text-center text-xs text-[var(--muted)]">
        Idle — no agent activity yet.
      </p>
    );
  }
  return (
    <ol className="space-y-2 font-[family-name:var(--font-mono)] text-[0.7rem] leading-relaxed">
      {events.map((event) => (
        <li key={event.id} className="flex min-w-0 items-start gap-2">
          <span
            className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ backgroundColor: STATUS_COLOR[event.status] ?? "var(--muted)" }}
          />
          <span className="min-w-0">
            <span className="text-[var(--muted)]">
              {new Date(event.ts).toLocaleTimeString()}{" "}
            </span>
            <span className="text-[var(--brand-500)]">{event.agent}</span>{" "}
            <span className="break-words">{event.message}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

function LiveBadge({ connected, count }: { connected: boolean; count: number }) {
  return (
    <span className="flex items-center gap-1.5 text-[0.65rem] font-medium text-[var(--muted)]">
      <span className="relative flex h-2 w-2">
        {connected && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--success)] opacity-70" />
        )}
        <span
          className="relative inline-flex h-2 w-2 rounded-full"
          style={{
            backgroundColor: connected ? "var(--success)" : "var(--muted)",
          }}
        />
      </span>
      {connected ? `${count} events` : "offline"}
    </span>
  );
}

/** Desktop: collapsible right column. */
export function AgentStreamColumn() {
  const { events, connected } = useAgentStream();
  const [open, setOpen] = useState(true);

  return (
    <aside
      className={cn(
        "hidden border-l border-[var(--border)] bg-[var(--surface)] lg:flex lg:flex-col",
        "transition-[width] duration-[var(--dur)] ease-[var(--ease)]",
        open ? "w-[20rem]" : "w-12",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? "Collapse agent stream" : "Expand agent stream"}
        className={cn(
          "flex h-12 shrink-0 items-center gap-2 border-b border-[var(--border)] px-3",
          "text-sm font-medium transition-colors",
          "hover:bg-[color-mix(in_srgb,var(--brand-400)_6%,transparent)]",
          open ? "justify-between" : "justify-center",
        )}
      >
        {open ? (
          <>
            <span className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-[var(--brand-500)]" />
              Agent stream
            </span>
            <LiveBadge connected={connected} count={events.length} />
          </>
        ) : (
          <Activity className="h-4 w-4 text-[var(--brand-500)]" />
        )}
      </button>

      {open && (
        <div className="min-w-0 flex-1 overflow-y-auto p-3">
          <EventList events={events} />
        </div>
      )}
    </aside>
  );
}

/**
 * Mobile: swipe-up drawer.
 *
 * Dragging the handle down past a threshold closes it, which is the gesture the
 * spec asks for; the tab is also a plain button so it stays usable without
 * gestures and for screen readers.
 */
export function AgentStreamDrawer() {
  const { events, connected } = useAgentStream();
  const [open, setOpen] = useState(false);
  const latest = events[0];

  return (
    <>
      {/* Peek tab — sits above the bottom nav */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-expanded={open}
        className={cn(
          "fixed inset-x-0 z-30 md:hidden",
          "bottom-[calc(3.5rem+env(safe-area-inset-bottom))]",
          "flex items-center gap-2 border-t border-[var(--border)]",
          "bg-[var(--surface)]/95 px-4 py-2 backdrop-blur-sm text-left",
        )}
      >
        <GripHorizontal className="h-4 w-4 shrink-0 text-[var(--muted)]" />
        <span className="min-w-0 flex-1 truncate text-[0.7rem] text-[var(--muted)]">
          {latest ? (
            <>
              <span className="text-[var(--brand-500)]">{latest.agent}</span>{" "}
              {latest.message}
            </>
          ) : (
            "Agent stream"
          )}
        </span>
        <LiveBadge connected={connected} count={events.length} />
      </button>

      <AnimatePresence>
        {open && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setOpen(false)}
              className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm md:hidden"
            />
            <motion.div
              role="dialog"
              aria-label="Agent stream"
              initial={{ y: "100%" }}
              animate={{ y: 0 }}
              exit={{ y: "100%" }}
              transition={{ type: "spring", damping: 32, stiffness: 320 }}
              drag="y"
              dragConstraints={{ top: 0, bottom: 0 }}
              dragElastic={{ top: 0, bottom: 0.4 }}
              onDragEnd={(_, info) => {
                if (info.offset.y > 100 || info.velocity.y > 500) setOpen(false);
              }}
              className={cn(
                "fixed inset-x-0 bottom-0 z-50 md:hidden",
                "max-h-[75dvh] rounded-t-[var(--r-lg)] border-t border-[var(--border)]",
                "bg-[var(--elevated)] shadow-[var(--shadow-2)]",
                "pb-[env(safe-area-inset-bottom)]",
              )}
            >
              <div className="flex cursor-grab items-center justify-center pt-2 active:cursor-grabbing">
                <span className="h-1 w-10 rounded-full bg-[var(--border)]" />
              </div>
              <div className="flex items-center justify-between px-4 py-2">
                <span className="flex items-center gap-2 text-sm font-medium">
                  <Activity className="h-4 w-4 text-[var(--brand-500)]" />
                  Agent stream
                </span>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  aria-label="Close agent stream"
                  className="rounded-[var(--r-sm)] p-1.5 text-[var(--muted)] hover:text-[var(--text)]"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="max-h-[58dvh] overflow-y-auto px-4 pb-4">
                <EventList events={events} />
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="flex w-full items-center justify-center gap-1 py-2 text-[0.7rem] text-[var(--muted)]"
              >
                <ChevronDown className="h-3 w-3" /> Swipe down to close
              </button>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
