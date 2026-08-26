import { create } from "zustand";
import { api } from "@/lib/api";

/**
 * Trip booking marks — the traveller's "I booked this" flags for flights/hotels.
 * Loaded once per session and shared by every flight/hotel card, so a booked
 * option shows as booked in the live trip AND in saved/history snapshots. Marks
 * are content-keyed (item_key), which is what makes them survive the active↔saved
 * trip re-save churn.
 */

export type BookingMark = {
  id: string;
  item_kind: string;
  direction: string;
  item_key: string;
  title: string | null;
  provider: string | null;
  price_amount: number | null;
  price_currency: string | null;
  booking_ref: string | null;
  status: string;
  check_in: string | null;
  source: string | null;
  snapshot: unknown;
  created_at: string | null;
};

export type MarkInput = {
  item_kind: "flight" | "hotel";
  item_key: string;
  direction?: string;
  title?: string | null;
  provider?: string | null;
  price_amount?: number | null;
  price_currency?: string | null;
  booking_ref?: string;
  check_in?: string;
  source?: string;
  snapshot?: unknown;
};

type State = {
  marks: BookingMark[];
  loaded: boolean;
  loading: boolean;
  load: () => Promise<void>;
  add: (input: MarkInput) => Promise<void>;
  remove: (id: string) => Promise<void>;
};

export const useBookings = create<State>((set, get) => ({
  marks: [],
  loaded: false,
  loading: false,
  load: async () => {
    if (get().loaded || get().loading) return;
    set({ loading: true });
    try {
      const r = await api.get<{ bookings: BookingMark[] }>("/trip/bookings");
      set({ marks: r.bookings ?? [], loaded: true, loading: false });
    } catch {
      set({ loaded: true, loading: false });
    }
  },
  add: async (input) => {
    const r = await api.post<{ booking: BookingMark }>("/trip/bookings", input);
    set((s) => ({
      marks: [
        r.booking,
        ...s.marks.filter((m) => !(m.item_key === r.booking.item_key && m.direction === r.booking.direction)),
      ],
    }));
  },
  remove: async (id) => {
    await api.del(`/trip/bookings/${id}`);
    set((s) => ({ marks: s.marks.filter((m) => m.id !== id) }));
  },
}));

const norm = (s: string) => (s || "").toLowerCase().replace(/\s+/g, " ").trim().slice(0, 120);

/** Stable content key for a flight option (route/carrier live in the title). */
export function flightKey(title: string, price?: number | null): string {
  return `f:${norm(title)}:${price ?? ""}`;
}
/** Stable content key for a hotel option. */
export function hotelKey(title: string): string {
  return `h:${norm(title)}`;
}
