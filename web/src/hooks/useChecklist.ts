import { useCallback, useEffect, useState } from "react";

/**
 * Per-trip "done" checklist, persisted in localStorage so it survives reloads
 * AND works offline (no network) — a living reference the traveller ticks off on
 * the ground. Keyed by a stable trip key (destination + start date).
 */
export function useChecklist(tripKey: string) {
  const storageKey = `journava:checklist:${tripKey}`;
  const [done, setDone] = useState<Set<string>>(new Set());

  // Reload when the trip changes.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      setDone(new Set(raw ? (JSON.parse(raw) as string[]) : []));
    } catch {
      setDone(new Set());
    }
  }, [storageKey]);

  const toggle = useCallback(
    (key: string) => {
      setDone((prev) => {
        const next = new Set(prev);
        next.has(key) ? next.delete(key) : next.add(key);
        try {
          localStorage.setItem(storageKey, JSON.stringify([...next]));
        } catch {
          /* storage may be unavailable (private mode) — the toggle still works in-session */
        }
        return next;
      });
    },
    [storageKey],
  );

  const isDone = useCallback((key: string) => done.has(key), [done]);
  return { done, toggle, isDone };
}
