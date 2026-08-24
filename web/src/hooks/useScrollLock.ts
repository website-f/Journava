import { useEffect } from "react";

/**
 * Locks page scroll while an overlay is open, compensating for the scrollbar
 * width so the layout never shifts (spec §10.6). Handles nested overlays.
 *
 * The attribute goes on <html>, not <body>. `body { overflow: hidden }` looks
 * like it should work but silently doesn't here: body's overflow only propagates
 * to the viewport while the ROOT element's own overflow computes to `visible`,
 * and globals.css sets `html { overflow-x: clip }`. So the lock has to be applied
 * to the element that actually scrolls — see `html[data-scroll-locked]`.
 */
let lockCount = 0;

export function useScrollLock(active: boolean) {
  useEffect(() => {
    if (!active) return;

    const root = document.documentElement;
    if (lockCount === 0) {
      const gap = window.innerWidth - root.clientWidth;
      root.dataset.scrollLocked = "true";
      if (gap > 0) root.style.paddingRight = `${gap}px`;
    }
    lockCount += 1;

    return () => {
      lockCount -= 1;
      if (lockCount === 0) {
        delete root.dataset.scrollLocked;
        root.style.paddingRight = "";
      }
    };
  }, [active]);
}
