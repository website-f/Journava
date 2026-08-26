import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { MapPin, Sparkles, CheckCircle2, X, Users, Search } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";

type Room = {
  id: string;
  title: string;
  property_name: string;
  city: string;
  price_amount: number | null;
  price_currency: string;
  original_price: number | null;
  discount_pct: number | null;
  description: string | null;
  image_url: string | null;
  amenities: string[];
  capacity: number | null;
  halal_friendly?: boolean;
  star_rating?: number | null;
};
type Site = {
  found: boolean;
  profile?: { name: string | null; logo_url: string | null; about: string | null; slug: string };
  cities?: string[];
  rooms?: Room[];
};

/**
 * Public, no-account hotel storefront (/h/:slug) — the business's own
 * Booking.com-style page: their logo + rooms with images, prices, discounts and
 * amenities, filterable, booked direct (simulated payment, double-booking
 * guarded server-side). Rendered before the auth wall.
 */
export function PublicHotelSite() {
  const { slug = "" } = useParams();
  const [site, setSite] = useState<Site | null>(null);
  const [q, setQ] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [guests, setGuests] = useState("");
  const [booking, setBooking] = useState<Room | null>(null);

  useEffect(() => {
    api.get<Site>(`/hotels/${slug}`).then(setSite).catch(() => setSite({ found: false }));
  }, [slug]);

  // Client-side SEO — SPA has no SSR, so set title/description from the hotel.
  useEffect(() => {
    if (site?.found && site.profile) {
      const name = site.profile.name || "Hotel";
      document.title = `${name} — book direct`;
      let m = document.querySelector('meta[name="description"]');
      if (!m) { m = document.createElement("meta"); m.setAttribute("name", "description"); document.head.appendChild(m); }
      m.setAttribute("content", site.profile.about || `Book rooms directly with ${name}.`);
    }
    return () => { document.title = "Journava — Travel, run by agents"; };
  }, [site]);

  const rooms = useMemo(() => {
    const all = site?.rooms ?? [];
    const term = q.trim().toLowerCase();
    const cap = Number(guests) || 0;
    const cap$ = Number(maxPrice) || 0;
    return all.filter((r) => {
      if (term && !`${r.title} ${r.property_name} ${r.city}`.toLowerCase().includes(term)) return false;
      if (cap && (r.capacity ?? 99) < cap) return false;
      if (cap$ && (r.price_amount ?? 0) > cap$) return false;
      return true;
    });
  }, [site, q, guests, maxPrice]);

  if (site === null) return <Centered>Loading…</Centered>;
  if (!site.found) {
    return (
      <Centered>
        <p className="text-lg font-semibold">This hotel page isn&rsquo;t available.</p>
        <p className="text-sm text-[var(--muted)]">Ask the hotel for a fresh link.</p>
      </Centered>
    );
  }
  const p = site.profile!;

  return (
    <div className="min-h-[100dvh] bg-[var(--bg)] text-[var(--text)]">
      {/* Hotel header */}
      <header className="border-b border-[var(--border)] bg-[var(--surface)]">
        <div className="mx-auto flex w-full max-w-5xl items-center gap-3 px-4 py-4">
          {p.logo_url ? (
            <img src={p.logo_url} alt={p.name ?? ""} className="h-11 w-11 rounded-[var(--r-md)] object-cover" />
          ) : (
            <span className="grid h-11 w-11 place-items-center rounded-[var(--r-md)] bg-[var(--brand-500)] text-white"><MapPin className="h-5 w-5" /></span>
          )}
          <div className="min-w-0">
            <h1 className="truncate font-[family-name:var(--font-display)] text-xl font-bold">{p.name}</h1>
            <p className="truncate text-xs text-[var(--muted)]">{p.about}</p>
          </div>
          <span className="ml-auto hidden shrink-0 rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--success)_14%,transparent)] px-2.5 py-1 text-[0.7rem] font-semibold text-[var(--success)] sm:block">
            Direct rates · no booking fee
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 py-6">
        {/* Filters */}
        <div className="mb-5 grid gap-2 rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--surface)] p-3 sm:grid-cols-[1fr_auto_auto]">
          <label className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3">
            <Search className="h-4 w-4 text-[var(--muted)]" />
            <input className="w-full bg-transparent py-2 text-sm outline-none" placeholder="Search rooms" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <label className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3">
            <Users className="h-4 w-4 text-[var(--muted)]" />
            <input type="number" min={1} className="w-20 bg-transparent py-2 text-sm outline-none" placeholder="Guests" value={guests} onChange={(e) => setGuests(e.target.value)} />
          </label>
          <label className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3">
            <span className="text-xs text-[var(--muted)]">Max/night</span>
            <input type="number" min={0} className="w-24 bg-transparent py-2 text-sm outline-none" placeholder="Any" value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} />
          </label>
        </div>

        <p className="mb-3 text-sm text-[var(--muted)]">{rooms.length} room{rooms.length === 1 ? "" : "s"} available</p>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {rooms.map((r) => (
            <div key={r.id} className="surface-card flex flex-col overflow-hidden p-0">
              <div className="relative h-40 w-full overflow-hidden bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)]">
                {r.image_url && <img src={r.image_url} alt={r.title} loading="lazy" className="h-full w-full object-cover" />}
                {r.discount_pct ? <span className="absolute left-2 top-2 rounded-[var(--r-pill)] bg-[var(--success)] px-2 py-0.5 text-[0.65rem] font-bold text-white">-{r.discount_pct}%</span> : null}
                {r.halal_friendly && <span className="absolute right-2 top-2 rounded-[var(--r-pill)] bg-black/50 px-2 py-0.5 text-[0.6rem] font-semibold text-white backdrop-blur-sm">halal-friendly</span>}
              </div>
              <div className="flex min-w-0 flex-1 flex-col p-3">
                <p className="truncate text-sm font-semibold">{r.title}</p>
                <p className="flex items-center gap-1 text-[0.7rem] text-[var(--muted)]"><MapPin className="h-3 w-3" />{r.property_name} · {r.city}{r.star_rating ? ` · ${"★".repeat(Math.min(5, r.star_rating))}` : ""}</p>
                {r.description && <p className="mt-1 line-clamp-2 text-xs text-[var(--muted)]">{r.description}</p>}
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {(r.amenities ?? []).slice(0, 4).map((a) => <span key={a} className="rounded-[var(--r-pill)] bg-[var(--bg)] px-1.5 py-0.5 text-[0.6rem] text-[var(--muted)]">{a}</span>)}
                </div>
                <div className="mt-auto flex items-end justify-between gap-2 pt-3">
                  <div>
                    {r.original_price && r.original_price > (r.price_amount ?? 0) ? <span className="mr-1 text-xs text-[var(--muted)] line-through">{r.price_currency} {r.original_price.toLocaleString()}</span> : null}
                    <span className="text-base font-bold text-[var(--brand-600)]">{r.price_currency} {(r.price_amount ?? 0).toLocaleString()}</span>
                    <span className="text-[0.65rem] text-[var(--muted)]">/night</span>
                  </div>
                  <Button size="sm" onClick={() => setBooking(r)}>Book</Button>
                </div>
              </div>
            </div>
          ))}
        </div>
        {rooms.length === 0 && <p className="py-10 text-center text-sm text-[var(--muted)]">No rooms match your filters.</p>}
      </main>

      {booking && <BookDialog slug={slug} room={booking} onClose={() => setBooking(null)} />}
    </div>
  );
}

function BookDialog({ slug, room, onClose }: { slug: string; room: Room; onClose: () => void }) {
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [checkIn, setCheckIn] = useState("");
  const [checkOut, setCheckOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ status: string; payment_ref?: string; amount?: number; currency?: string; reason?: string } | null>(null);

  const nights = useMemo(() => {
    if (!checkIn || !checkOut) return 1;
    const d = (new Date(checkOut).getTime() - new Date(checkIn).getTime()) / 86400000;
    return d > 0 ? Math.round(d) : 1;
  }, [checkIn, checkOut]);

  const pay = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const r = await api.post<{ status: string; payment_ref?: string; amount?: number; currency?: string; reason?: string }>(
        `/hotels/${slug}/book`,
        { listing_id: room.id, guest_name: name, guest_contact: contact, check_in: checkIn || undefined, check_out: checkOut || undefined, nights },
      );
      setResult(r);
    } catch {
      setResult({ status: "error", reason: "Payment couldn't be processed — try again." });
    } finally {
      setBusy(false);
    }
  };

  const total = (room.price_amount ?? 0) * nights;

  return (
    <div className="fixed inset-0 z-[80] grid place-items-center bg-black/50 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-md rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--elevated)] p-5 shadow-[var(--shadow-2)]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <h3 className="font-[family-name:var(--font-display)] text-lg font-bold">{room.title}</h3>
            <p className="text-xs text-[var(--muted)]">{room.property_name}</p>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-full p-1 text-[var(--muted)] hover:text-[var(--text)]"><X className="h-4 w-4" /></button>
        </div>

        {result?.status === "confirmed" ? (
          <div className="mt-4 grid place-items-center gap-3 py-4 text-center">
            <CheckCircle2 className="h-12 w-12 text-[var(--success)]" weight="fill" />
            <p className="text-lg font-semibold">Booking confirmed!</p>
            <p className="text-sm text-[var(--muted)]">
              {result.currency} {result.amount?.toLocaleString()} paid · ref <span className="font-[family-name:var(--font-mono)]">{result.payment_ref}</span>
            </p>
            <p className="text-xs text-[var(--muted)]">A simulated payment for this demo — no real charge.</p>
            <Button className="mt-1 w-full" variant="secondary" onClick={onClose}>Done</Button>
          </div>
        ) : result && result.status !== "confirmed" ? (
          <div className="mt-4 rounded-[var(--r-md)] border-l-2 border-[var(--warning)] bg-[color-mix(in_srgb,var(--warning)_8%,transparent)] p-3">
            <p className="text-sm font-semibold text-[var(--warning)]">{result.reason || "Couldn't complete the booking."}</p>
            <Button className="mt-3 w-full" variant="secondary" onClick={() => setResult(null)}>Back</Button>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <label className="block"><span className="mb-1 block text-xs text-[var(--muted)]">Check-in</span><input type="date" className={INPUT} value={checkIn} onChange={(e) => setCheckIn(e.target.value)} /></label>
              <label className="block"><span className="mb-1 block text-xs text-[var(--muted)]">Check-out</span><input type="date" className={INPUT} value={checkOut} onChange={(e) => setCheckOut(e.target.value)} /></label>
            </div>
            <input className={INPUT} placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
            <input className={INPUT} placeholder="Email or phone" value={contact} onChange={(e) => setContact(e.target.value)} />
            <div className="flex items-center justify-between rounded-[var(--r-md)] bg-[var(--bg)] px-3 py-2 text-sm">
              <span className="text-[var(--muted)]">{nights} night{nights === 1 ? "" : "s"}</span>
              <span className="font-semibold">{room.price_currency} {total.toLocaleString()}</span>
            </div>
            <Button className="w-full" loading={busy} disabled={!name.trim()} onClick={() => void pay()}>
              <Sparkles className="h-4 w-4" /> Pay {room.price_currency} {total.toLocaleString()} &amp; confirm
            </Button>
            <p className="text-center text-[0.65rem] text-[var(--muted)]">Simulated payment for this demo — no real charge.</p>
          </div>
        )}
      </div>
    </div>
  );
}

const INPUT = "w-full rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5 text-sm";

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="grid min-h-[100dvh] place-items-center gap-2 bg-[var(--bg)] px-6 text-center">{children}</div>;
}
