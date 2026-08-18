import { useEffect } from "react";

/**
 * Locks body scroll while an overlay is open, compensating for the scrollbar
 * width so the layout never shifts (spec §10.6). Handles nested overlays.
 */
let lockCount = 0;

export function useScrollLock(active: boolean) {
  useEffect(() => {
    if (!active) return;

    if (lockCount === 0) {
      const gap = window.innerWidth - document.documentElement.clientWidth;
      document.body.dataset.scrollLocked = "true";
      if (gap > 0) document.body.style.paddingRight = `${gap}px`;
    }
    lockCount += 1;

    return () => {
      lockCount -= 1;
      if (lockCount === 0) {
        delete document.body.dataset.scrollLocked;
        document.body.style.paddingRight = "";
      }
    };
  }, [active]);
}
