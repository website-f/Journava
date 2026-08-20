import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles, Compass, Bot, Plus, X } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { useAgentStream } from "@/hooks/useAgentStream";
import { usePlanStore } from "@/stores/planStore";

/**
 * AssistiveTouch-style quick launcher — a draggable floating button that snaps
 * to the nearest screen edge (position remembered), and taps open a small glass
 * menu of high-value actions. Distinct from the bottom nav: this is the "always
 * one thumb away" shortcut, especially handy as an installed PWA.
 */

const SIZE = 52; // px
const MARGIN = 12; // px from the edge
const DRAG_THRESHOLD = 6; // px before a press counts as a drag, not a tap
const STORAGE_KEY = "journava.assist.pos";

type Pos = { x: number; y: number };

function clamp(pos: Pos): Pos {
  const maxX = window.innerWidth - SIZE - MARGIN;
  // Keep clear of the top bar and the floating bottom nav.
  const minY = MARGIN + 56;
  const maxY = window.innerHeight - SIZE - MARGIN - 96;
  return {
    x: Math.min(Math.max(MARGIN, pos.x), Math.max(MARGIN, maxX)),
    y: Math.min(Math.max(minY, pos.y), Math.max(minY, maxY)),
  };
}

function loadPos(): Pos {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return clamp(JSON.parse(raw) as Pos);
  } catch {
    /* ignore */
  }
  return clamp({ x: window.innerWidth - SIZE - MARGIN, y: Math.round(window.innerHeight * 0.52) });
}

export function AssistiveTouch() {
  const navigate = useNavigate();
  const { events } = useAgentStream();
  const jobRunning = usePlanStore((s) => s.jobRunning);
  const latest = events.find((e) => e.agent !== "system") ?? events[0];
  const [pos, setPos] = useState<Pos>(loadPos);
  const [open, setOpen] = useState(false);
  const drag = useRef({ startX: 0, startY: 0, dx: 0, dy: 0, moved: false, active: false });

  useEffect(() => {
    const onResize = () => setPos((p) => clamp(p));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const onPointerDown = (e: ReactPointerEvent) => {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = {
      startX: e.clientX,
      startY: e.clientY,
      dx: e.clientX - pos.x,
      dy: e.clientY - pos.y,
      moved: false,
      active: true,
    };
  };

  const onPointerMove = (e: ReactPointerEvent) => {
    const d = drag.current;
    if (!d.active) return;
    if (!d.moved && Math.hypot(e.clientX - d.startX, e.clientY - d.startY) > DRAG_THRESHOLD) {
      d.moved = true;
      setOpen(false);
    }
    if (d.moved) setPos(clamp({ x: e.clientX - d.dx, y: e.clientY - d.dy }));
  };

  const onPointerUp = () => {
    const d = drag.current;
    if (!d.active) return;
    d.active = false;
    if (d.moved) {
      setPos((prev) => {
        const snappedX =
          prev.x + SIZE / 2 < window.innerWidth / 2 ? MARGIN : window.innerWidth - SIZE - MARGIN;
        const next = clamp({ x: snappedX, y: prev.y });
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        } catch {
          /* ignore */
        }
        return next;
      });
    } else {
      setOpen((o) => !o);
    }
  };

  const onLeftHalf = pos.x + SIZE / 2 < window.innerWidth / 2;

  const go = (to: string) => {
    setOpen(false);
    navigate(to);
  };

  const ACTIONS = [
    { label: "New plan", icon: Plus, to: "/" },
    { label: "Research", icon: Compass, to: "/research" },
    { label: "Agents", icon: Bot, to: "/agents" },
  ];

  return (
    <div
      className="fixed z-[60] select-none"
      style={{ left: pos.x, top: pos.y, width: SIZE, height: SIZE, touchAction: "none" }}
    >
      {open && (
        <div
          className={cn(
            "glass-strong absolute bottom-full mb-3 w-56 rounded-[var(--r-lg)] p-1.5 shadow-[var(--shadow-2)]",
            onLeftHalf ? "left-0" : "right-0",
          )}
        >
          {jobRunning && (
            <button
              onClick={() => go("/agents")}
              className="mb-1 flex w-full items-start gap-2.5 rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)] px-3 py-2 text-left"
            >
              <span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center">
                <span className="h-2 w-2 animate-ping rounded-full bg-[var(--brand-500)]" />
              </span>
              <span className="min-w-0">
                <span className="block text-xs font-semibold text-[var(--brand-500)]">Agents working…</span>
                <span className="block truncate text-[0.65rem] text-[var(--muted)]">
                  {latest ? `${latest.agent}: ${latest.message}` : "in progress — tap to watch"}
                </span>
              </span>
            </button>
          )}
          {ACTIONS.map(({ label, icon: Icon, to }) => (
            <button
              key={to}
              onClick={() => go(to)}
              className="flex w-full items-center gap-2.5 rounded-[var(--r-md)] px-3 py-2 text-sm font-medium text-[var(--text)] hover:bg-[color-mix(in_srgb,var(--brand-400)_10%,transparent)]"
            >
              <Icon className="h-4 w-4 text-[var(--brand-500)]" />
              {label}
            </button>
          ))}
        </div>
      )}

      {jobRunning && !open && (
        <span className="pointer-events-none absolute inset-0 animate-ping rounded-full bg-[color-mix(in_srgb,var(--brand-400)_35%,transparent)]" />
      )}
      <button
        aria-label="Quick actions"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        className={cn(
          "glass-strong relative grid h-[52px] w-[52px] place-items-center rounded-full shadow-[var(--shadow-2)]",
          "text-[var(--brand-500)] transition-transform active:scale-95 touch-none",
          jobRunning && "ring-2 ring-[var(--brand-400)]",
        )}
      >
        {open ? <X className="h-5 w-5" /> : <Sparkles className="h-5 w-5" />}
        {jobRunning && !open && (
          <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-[var(--brand-500)] ring-2 ring-[var(--bg)]" />
        )}
      </button>
    </div>
  );
}
