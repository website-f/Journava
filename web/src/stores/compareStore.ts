import { create } from "zustand";

/**
 * The comparison "cart" — saved-trip ids the traveller ticked to compare, held
 * client-side and persisted so the tray survives reloads. The comparison page
 * fetches each trip's facts from these ids.
 */
const KEY = "journava:compare";
const MAX = 4; // a side-by-side table stays readable up to ~4 columns

function load(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string").slice(0, MAX) : [];
  } catch {
    return [];
  }
}

function save(ids: string[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(ids));
  } catch {
    /* private mode — the in-memory store still works this session */
  }
}

interface CompareState {
  ids: string[];
  add: (id: string) => boolean; // false if it didn't fit (already at MAX)
  remove: (id: string) => void;
  toggle: (id: string) => void;
  clear: () => void;
  has: (id: string) => boolean;
}

export const MAX_COMPARE = MAX;

export const useCompareStore = create<CompareState>((set, get) => ({
  ids: load(),
  add: (id) => {
    const { ids } = get();
    if (ids.includes(id)) return true;
    if (ids.length >= MAX) return false;
    const next = [...ids, id];
    save(next);
    set({ ids: next });
    return true;
  },
  remove: (id) => {
    const next = get().ids.filter((x) => x !== id);
    save(next);
    set({ ids: next });
  },
  toggle: (id) => {
    const { ids, add, remove } = get();
    if (ids.includes(id)) remove(id);
    else add(id);
  },
  clear: () => {
    save([]);
    set({ ids: [] });
  },
  has: (id) => get().ids.includes(id),
}));
