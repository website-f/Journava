import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { MapPin, Sparkles, CheckCircle2, X, Users, Search, Bot, Building2, ChevronDown } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { PlaceImage } from "@/components/ui/PlaceImage";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

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
  image_urls?: string[];
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
  const [sort, setSort] = useState<"recommended" | "price_asc" | "price_desc">("recommended");
  const [booking, setBooking] = useState<Room | null>(null);
  const [details, setDetails] = useState<Room | null>(null);
  const [highlight, setHighlight] = useState<string[]>([]);

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
    const filtered = all.filter((r) => {
      if (term && !`${r.title} ${r.property_name} ${r.city}`.toLowerCase().includes(term)) return false;
      if (cap && (r.capacity ?? 99) < cap) return false;
      if (cap$ && (r.price_amount ?? 0) > cap$) return false;
      return true;
    });
    const price = (r: Room) => r.price_amount ?? Number.POSITIVE_INFINITY;
    if (sort === "price_asc") return [...filtered].sort((a, b) => price(a) - price(b));
    if (sort === "price_desc") return [...filtered].sort((a, b) => price(b) - price(a));
    return filtered;
  }, [site, q, guests, maxPrice, sort]);

  const cheapest = useMemo(() => {
    const priced = (site?.rooms ?? []).map((r) => r.price_amount).filter((n): n is number => typeof n === "number" && n > 0);
    return priced.length ? Math.min(...priced) : null;
  }, [site]);

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
      {/* Hero — a Trip.com-style banner: brand gradient, the property identity,
          and a search card that overlaps the fold. */}
      <header className="relative overflow-hidden bg-gradient-to-br from-[var(--brand-600)] to-[var(--brand-400)] text-white">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-25"
          style={{ backgroundImage: "radial-gradient(circle at 88% 12%, rgba(255,255,255,0.55) 0, transparent 42%), radial-gradient(circle at 10% 90%, rgba(255,255,255,0.28) 0, transparent 40%)" }}
        />
        <div className="relative mx-auto flex w-full max-w-5xl items-start gap-3 px-4 pb-8 pt-8">
          {p.logo_url ? (
            <img src={p.logo_url} alt={p.name ?? ""} className="h-14 w-14 shrink-0 rounded-[var(--r-lg)] object-cover ring-2 ring-white/40" />
          ) : (
            <span className="grid h-14 w-14 shrink-0 place-items-center rounded-[var(--r-lg)] bg-white/20 ring-2 ring-white/40"><Building2 className="h-6 w-6" /></span>
          )}
          <div className="min-w-0 flex-1">
            <p className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-white/80">Book direct</p>
            <h1 className="mt-0.5 font-[family-name:var(--font-display)] text-2xl font-bold leading-tight tracking-tight sm:text-3xl">{p.name}</h1>
            {p.about && <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-white/85">{p.about}</p>}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-[var(--r-pill)] bg-white/15 px-2.5 py-1 text-[0.7rem] font-semibold ring-1 ring-white/25">
                <CheckCircle2 className="h-3.5 w-3.5" /> Direct rates · no booking fee
              </span>
              {(site.cities ?? []).slice(0, 3).map((c) => (
                <span key={c} className="inline-flex items-center gap-1 rounded-[var(--r-pill)] bg-white/10 px-2.5 py-1 text-[0.7rem] font-medium ring-1 ring-white/20">
                  <MapPin className="h-3 w-3" /> {c}
                </span>
              ))}
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 pb-16 pt-5">
        {/* Search / filter card — sits cleanly below the hero (no overlap). */}
        <div className="rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--elevated)] p-3 shadow-[var(--shadow-1)]">
          <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto]">
            <label className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3">
              <Search className="h-4 w-4 text-[var(--muted)]" />
              <input className="w-full bg-transparent py-2.5 text-sm outline-none" placeholder="Search rooms, area…" value={q} onChange={(e) => setQ(e.target.value)} />
            </label>
            <label className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3">
              <Users className="h-4 w-4 text-[var(--muted)]" />
              <input type="number" min={1} className="w-full bg-transparent py-2.5 text-sm outline-none sm:w-24" placeholder="Guests" value={guests} onChange={(e) => setGuests(e.target.value)} />
            </label>
            <label className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3">
              <span className="text-xs text-[var(--muted)]">Max/night</span>
              <input type="number" min={0} className="w-full bg-transparent py-2.5 text-sm outline-none sm:w-24" placeholder="Any" value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} />
            </label>
          </div>
          {(q || guests || maxPrice) && (
            <button onClick={() => { setQ(""); setGuests(""); setMaxPrice(""); }} className="mt-2 text-xs font-medium text-[var(--muted)] hover:text-[var(--brand-600)]">
              Clear filters
            </button>
          )}
        </div>

        {/* Results toolbar: count + sort */}
        <div className="mb-4 mt-5 flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm">
            <span className="font-semibold">{rooms.length}</span> <span className="text-[var(--muted)]">room{rooms.length === 1 ? "" : "s"}{cheapest != null ? ` · from ${site.rooms?.[0]?.price_currency ?? "MYR"} ${cheapest.toLocaleString()}/night` : ""}</span>
          </p>
          <label className="flex items-center gap-2 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-xs">
            <ChevronDown className="h-3.5 w-3.5 text-[var(--muted)]" />
            <select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} className="bg-transparent font-medium outline-none">
              <option value="recommended">Recommended</option>
              <option value="price_asc">Price: low to high</option>
              <option value="price_desc">Price: high to low</option>
            </select>
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {rooms.map((r) => {
            const shots = r.image_urls?.length ? r.image_urls : r.image_url ? [r.image_url] : [];
            return (
              <div key={r.id} className={cn("surface-card group flex flex-col overflow-hidden p-0 transition-shadow hover:shadow-[var(--shadow-2)]", highlight.includes(r.id) && "ring-2 ring-[var(--brand-400)]")}>
                <button onClick={() => setDetails(r)} className="relative block aspect-[4/3] w-full overflow-hidden text-left">
                  {shots[0] ? (
                    <img src={shots[0]} alt={r.title} loading="lazy" className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.04]" />
                  ) : (
                    // No uploaded photo → fetch a representative one for the property,
                    // falling back to a branded placeholder if none is found.
                    <PlaceImage
                      query={r.property_name || r.title}
                      city={r.city}
                      alt={r.title}
                      className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.04]"
                      fallback={
                        <span className="flex h-full w-full flex-col items-center justify-center gap-1 bg-gradient-to-br from-[color-mix(in_srgb,var(--brand-400)_22%,transparent)] to-[color-mix(in_srgb,var(--brand-500)_10%,transparent)] text-[var(--brand-600)]">
                          <Building2 className="h-8 w-8 opacity-70" />
                          <span className="text-[0.65rem] font-medium opacity-70">{r.property_name}</span>
                        </span>
                      }
                    />
                  )}
                  {r.discount_pct ? <span className="absolute left-2 top-2 rounded-[var(--r-pill)] bg-[var(--success)] px-2 py-0.5 text-[0.65rem] font-bold text-white shadow">-{r.discount_pct}%</span> : null}
                  {r.halal_friendly && <span className="absolute right-2 top-2 rounded-[var(--r-pill)] bg-black/50 px-2 py-0.5 text-[0.6rem] font-semibold text-white backdrop-blur-sm">halal-friendly</span>}
                  {shots.length > 1 && <span className="absolute bottom-2 right-2 rounded-[var(--r-pill)] bg-black/55 px-2 py-0.5 text-[0.6rem] font-semibold text-white">📷 {shots.length}</span>}
                </button>
                <div className="flex min-w-0 flex-1 flex-col p-3">
                  <p className="truncate text-sm font-semibold">{r.title}</p>
                  <p className="mt-0.5 flex items-center gap-1 truncate text-[0.7rem] text-[var(--muted)]"><MapPin className="h-3 w-3 shrink-0" />{r.property_name} · {r.city}{r.star_rating ? ` · ${"★".repeat(Math.min(5, r.star_rating))}` : ""}</p>
                  {r.description && <p className="mt-1 line-clamp-2 text-xs text-[var(--muted)]">{r.description}</p>}
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {(r.amenities ?? []).slice(0, 4).map((a) => <span key={a} className="rounded-[var(--r-pill)] bg-[var(--bg)] px-1.5 py-0.5 text-[0.6rem] text-[var(--muted)]">{a}</span>)}
                  </div>
                  <div className="mt-auto flex items-end justify-between gap-2 pt-3">
                    <div className="min-w-0">
                      {r.original_price && r.original_price > (r.price_amount ?? 0) ? <span className="mr-1 text-xs text-[var(--muted)] line-through">{r.price_currency} {r.original_price.toLocaleString()}</span> : null}
                      <span className="text-base font-bold text-[var(--brand-600)]">{r.price_currency} {(r.price_amount ?? 0).toLocaleString()}</span>
                      <span className="text-[0.65rem] text-[var(--muted)]">/night</span>
                    </div>
                    <Button size="sm" onClick={() => setDetails(r)}>View details</Button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        {rooms.length === 0 && <p className="py-10 text-center text-sm text-[var(--muted)]">No rooms match your filters.</p>}
      </main>

      {details && (
        <RoomDetails
          room={details}
          onClose={() => setDetails(null)}
          onBook={() => { setBooking(details); }}
        />
      )}
      {booking && <BookDialog slug={slug} room={booking} onClose={() => setBooking(null)} />}

      <RoomAssistant
        slug={slug}
        onHighlight={setHighlight}
        onOpenRoom={(id) => {
          const r = (site.rooms ?? []).find((x) => x.id === id);
          if (r) setDetails(r);
        }}
      />
    </div>
  );
}

/**
 * Booking.com-style details "page" — a full-screen overlay with a photo gallery,
 * the full description, every amenity, and a reserve panel. Book from here.
 */
function RoomDetails({ room, onClose, onBook }: { room: Room; onClose: () => void; onBook: () => void }) {
  const shots = room.image_urls?.length ? room.image_urls : room.image_url ? [room.image_url] : [];
  const [active, setActive] = useState(0);
  const hero = shots[active] ?? null;
  return (
    <div className="fixed inset-0 z-[70] overflow-y-auto bg-[var(--bg)]">
      <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
        <button onClick={onClose} aria-label="Back" className="rounded-full p-1.5 text-[var(--muted)] hover:bg-[var(--bg)] hover:text-[var(--text)]"><X className="h-5 w-5" /></button>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{room.title}</p>
          <p className="truncate text-xs text-[var(--muted)]">{room.property_name} · {room.city}</p>
        </div>
        <span className="ml-auto shrink-0 text-right">
          <span className="text-lg font-bold text-[var(--brand-600)]">{room.price_currency} {(room.price_amount ?? 0).toLocaleString()}</span>
          <span className="text-xs text-[var(--muted)]">/night</span>
        </span>
      </div>

      <div className="mx-auto grid w-full max-w-5xl gap-6 px-4 py-6 lg:grid-cols-[1.6fr_1fr]">
        <div>
          {/* Gallery */}
          <div className="overflow-hidden rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--surface)]">
            <div className="relative aspect-[16/10] w-full bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)]">
              {hero && <img src={hero} alt={room.title} className="h-full w-full object-cover" />}
              {room.discount_pct ? <span className="absolute left-3 top-3 rounded-[var(--r-pill)] bg-[var(--success)] px-2.5 py-1 text-xs font-bold text-white">-{room.discount_pct}% direct</span> : null}
            </div>
            {shots.length > 1 && (
              <div className="flex gap-2 overflow-x-auto p-2">
                {shots.map((s, i) => (
                  <button key={i} onClick={() => setActive(i)} className={cn("h-16 w-24 shrink-0 overflow-hidden rounded-[var(--r-sm)] border-2", i === active ? "border-[var(--brand-500)]" : "border-transparent opacity-70 hover:opacity-100")}>
                    <img src={s} alt={`view ${i + 1}`} className="h-full w-full object-cover" />
                  </button>
                ))}
              </div>
            )}
          </div>

          <h2 className="mt-5 font-[family-name:var(--font-display)] text-2xl font-bold tracking-tight">{room.title}</h2>
          <p className="mt-1 flex items-center gap-1.5 text-sm text-[var(--muted)]">
            <MapPin className="h-4 w-4" />{room.property_name} · {room.city}
            {room.star_rating ? <span className="text-[var(--warning)]">· {"★".repeat(Math.min(5, room.star_rating))}</span> : null}
            {room.capacity ? <span>· sleeps {room.capacity}</span> : null}
          </p>
          {room.description && <p className="mt-4 whitespace-pre-line text-sm leading-relaxed text-[var(--text)]">{room.description}</p>}

          {(room.amenities ?? []).length > 0 && (
            <>
              <h3 className="mt-6 text-sm font-semibold">What this room offers</h3>
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                {room.amenities.map((a) => (
                  <span key={a} className="flex items-center gap-1.5 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm">
                    <CheckCircle2 className="h-4 w-4 text-[var(--brand-500)]" /> {a}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Reserve panel */}
        <aside className="lg:sticky lg:top-20 lg:self-start">
          <div className="surface-card p-5">
            <div className="flex items-baseline gap-2">
              {room.original_price && room.original_price > (room.price_amount ?? 0) ? <span className="text-sm text-[var(--muted)] line-through">{room.price_currency} {room.original_price.toLocaleString()}</span> : null}
              <span className="text-2xl font-bold text-[var(--brand-600)]">{room.price_currency} {(room.price_amount ?? 0).toLocaleString()}</span>
              <span className="text-sm text-[var(--muted)]">/night</span>
            </div>
            <p className="mt-1 text-xs text-[var(--success)]">Direct rate · no OTA booking fee</p>
            <Button className="mt-4 w-full" onClick={onBook}><Sparkles className="h-4 w-4" /> Reserve this room</Button>
            {room.halal_friendly && <p className="mt-3 text-center text-xs text-[var(--muted)]">✅ Halal-friendly property</p>}
          </div>
        </aside>
      </div>
    </div>
  );
}

/**
 * On-site AI concierge — a floating launcher that opens a chat panel. It answers
 * only from this hotel's own rooms (server-side), highlights the ones it suggests
 * back on the page, and lets the guest jump straight into a room's details.
 */
type ChatMsg = { role: "user" | "ai"; text: string; rooms?: string[] };
function RoomAssistant({ slug, onHighlight, onOpenRoom }: { slug: string; onHighlight: (ids: string[]) => void; onOpenRoom: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [msgs, setMsgs] = useState<ChatMsg[]>([{ role: "ai", text: "Hi! Tell me what you're after — budget, how many guests, sea view, honeymoon… and I'll find the right room." }]);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, open]);

  const ask = async () => {
    const query = q.trim();
    if (!query || busy) return;
    setMsgs((m) => [...m, { role: "user", text: query }]);
    setQ("");
    setBusy(true);
    try {
      const r = await api.post<{ answer: string; room_ids: string[] }>(`/hotels/${slug}/assistant`, { query });
      setMsgs((m) => [...m, { role: "ai", text: r.answer, rooms: r.room_ids }]);
      onHighlight(r.room_ids ?? []);
    } catch {
      setMsgs((m) => [...m, { role: "ai", text: "Sorry — I couldn't reach the concierge just now. Please try again." }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-5 right-5 z-[60] flex items-center gap-2 rounded-[var(--r-pill)] bg-[var(--brand-500)] px-4 py-3 text-sm font-semibold text-white shadow-[var(--shadow-3)] transition-transform hover:bg-[var(--brand-600)] active:scale-95"
        >
          <Bot className="h-5 w-5" weight="duotone" /> Ask AI
        </button>
      )}
      {open && (
        <div className="fixed bottom-5 right-5 z-[60] flex h-[32rem] max-h-[calc(100dvh-2.5rem)] w-[calc(100vw-2.5rem)] max-w-sm flex-col overflow-hidden rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--elevated)] shadow-[var(--shadow-3)]">
          <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3">
            <span className="grid h-8 w-8 place-items-center rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_16%,transparent)] text-[var(--brand-500)]"><Bot className="h-4 w-4" weight="duotone" /></span>
            <div className="min-w-0"><p className="text-sm font-semibold">Booking assistant</p><p className="text-[0.7rem] text-[var(--muted)]">Answers from this hotel's rooms</p></div>
            <button onClick={() => setOpen(false)} aria-label="Close" className="ml-auto rounded-full p-1 text-[var(--muted)] hover:text-[var(--text)]"><X className="h-4 w-4" /></button>
          </div>
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
            {msgs.map((m, i) => (
              <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div className={cn("max-w-[85%] rounded-[var(--r-lg)] px-3 py-2 text-sm", m.role === "user" ? "bg-[var(--brand-500)] text-white" : "bg-[var(--bg)] text-[var(--text)]")}>
                  {m.text}
                  {!!m.rooms?.length && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {m.rooms.map((id) => (
                        <button key={id} onClick={() => { onOpenRoom(id); setOpen(false); }} className="rounded-[var(--r-pill)] border border-[var(--brand-400)] bg-[var(--surface)] px-2 py-0.5 text-xs font-medium text-[var(--brand-600)] hover:bg-[var(--bg)]">View room →</button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {busy && <p className="text-xs text-[var(--muted)]">Thinking…</p>}
            <div ref={endRef} />
          </div>
          <div className="flex items-center gap-2 border-t border-[var(--border)] p-3">
            <input
              className="min-w-0 flex-1 rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm outline-none focus:border-[var(--brand-400)]"
              placeholder="e.g. sea view for 2 under RM400"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void ask(); }}
            />
            <Button size="sm" loading={busy} onClick={() => void ask()}>Ask</Button>
          </div>
        </div>
      )}
    </>
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
