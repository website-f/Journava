import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { Headset } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { usePlanStore } from "@/stores/planStore";
import { AssistantPanel } from "./AssistantPanel";

/**
 * Floating AI-assistant launcher — a draggable button that snaps to the nearest
 * screen edge (position remembered), and taps open the Journava AI chat panel
 * (ask anything, upload an image, or kick off a background agent run). The
 * "always one thumb away" entry point, especially handy as an installed PWA.
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
  const jobRunning = usePlanStore((s) => s.jobRunning);
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
      setOpen(true);
    }
  };

  return (
    <>
      <div
        className="fixed z-[60] select-none"
        style={{ left: pos.x, top: pos.y, width: SIZE, height: SIZE, touchAction: "none" }}
      >
        {jobRunning && (
          <span className="pointer-events-none absolute inset-0 animate-ping rounded-full bg-[color-mix(in_srgb,var(--brand-400)_35%,transparent)]" />
        )}
        <button
          aria-label="Journava AI assistant"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          className={cn(
            "glass-strong relative grid h-[52px] w-[52px] place-items-center rounded-full shadow-[var(--shadow-2)]",
            "text-[var(--brand-500)] transition-transform active:scale-95 touch-none",
            jobRunning && "ring-2 ring-[var(--brand-400)]",
          )}
        >
          <Headset className="h-5 w-5" weight="fill" />
          {jobRunning && (
            <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-[var(--brand-500)] ring-2 ring-[var(--bg)]" />
          )}
        </button>
      </div>

      <AssistantPanel open={open} onOpenChange={setOpen} />
    </>
  );
}
