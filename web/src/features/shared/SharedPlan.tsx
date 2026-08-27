import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Sparkles, Calendar, Clock, MapPin, Users2, Wallet, Plane, Utensils, Compass, Bus, Building2, ExternalLink } from "@/components/ui/icons";
import { Button, Spinner } from "@/components/ui";
import { PlaceImage, mapsSearchUrl } from "@/components/ui/PlaceImage";
import { api, API_BASE } from "@/lib/api";
import { useAuth } from "@/providers/AuthProvider";
import { TripExtraPanels } from "@/features/command-center/ScopedResults";
import { GroupVote } from "./GroupVote";
import type { ItineraryItem, PlanResults } from "@/stores/planStore";

/**
 * Public, read-only view of a compiled plan — opened by a client with no account
 * from a shared link (`/s/:token`). A branded hero, a clear day-by-day itinerary
 * (which the generic panels omit) and then the rich interactive panels, so the
 * shared plan reads as a real trip document rather than a data dump.
 */

const fmtDate = (iso?: string): string => {
  if (!iso) return "";
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};
const dayDate = (start: string | undefined, dayIndex: number): string => {
  if (!start) return "";
  const d = new Date(`${String(start).slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return "";
  d.setDate(d.getDate() + Math.max(0, dayIndex - 1));
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
};

const KIND_ICON: Record<string, typeof Plane> = {
  flight: Plane, hotel: Building2, meal: Utensils, restaurant: Utensils, activity: Compass, transport: Bus,
};
const KIND_LABEL: Record<string, string> = {
  flight: "Flight", hotel: "Stay", meal: "Meal", restaurant: "Meal", activity: "Activity", transport: "Transport",
};

export function SharedPlan() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { status } = useAuth();
  const [state, setState] = useState<{ title: string; results: PlanResults } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const saveToMyTrips = async () => {
    if (status !== "authed") {
      toast.info("Sign in to Journava, then reopen this link to save the trip.");
      navigate("/");
      return;
    }
    setSaving(true);
    try {
      const res = await api.post<{ id?: string; error?: string }>("/saved/from-shared", { token });
      if (res.error) toast.error(res.error);
      else {
        toast.success("Saved to your trips!");
        navigate("/trip");
      }
    } catch {
      toast.error("Couldn't save this trip.");
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/shared/${token}`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        if (d.error || !d.results) setError(d.error || "This plan couldn't be loaded.");
        else setState({ title: d.title, results: d.results });
      })
      .catch(() => !cancelled && setError("This plan couldn't be loaded."));
    return () => {
      cancelled = true;
    };
  }, [token]);

  const meta = useMemo(() => {
    const results = state?.results;
    const chief = ((results?.chief?.data ?? {}) as Record<string, unknown>);
    const resolved = ((chief.resolved_request ?? {}) as Record<string, unknown>);
    const destination = (chief.destination as string) || (resolved.destination as string) || state?.title || "Your trip";
    const start = (resolved.start_date as string) || (chief.start_date as string) || "";
    const end = (resolved.end_date as string) || (chief.end_date as string) || "";
    const travellers = (resolved.travellers as number) || (chief.travellers as number) || null;
    const budget = results?.budget?.data as { currency?: string; spent_estimate?: number; breakdown?: { total_estimate?: number } } | undefined;
    const budgetTotal = budget?.spent_estimate ?? budget?.breakdown?.total_estimate ?? null;
    const items = (results?.itinerary?.items ?? []) as ItineraryItem[];
    const overview = (results?.concierge?.summary || results?.recommendation?.summary || "").trim();
    return { destination, start, end, travellers, budgetCurrency: budget?.currency || "", budgetTotal, items, overview };
  }, [state]);

  const byDay = useMemo(() => {
    const map = new Map<number, ItineraryItem[]>();
    for (const it of meta.items) {
      const d = Number(it.day_index) || 1;
      (map.get(d) ?? map.set(d, []).get(d)!).push(it);
    }
    return [...map.entries()].sort(([a], [b]) => a - b);
  }, [meta.items]);

  const dateLabel = meta.start ? `${fmtDate(meta.start)}${meta.end ? ` – ${fmtDate(meta.end)}` : ""}` : "";

  return (
    <div className="min-h-[100dvh] bg-[var(--bg)] text-[var(--text)]">
      {/* Sticky slim bar — brand mark + Save, always reachable while scrolling. */}
      <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-[var(--surface)]/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-3">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-[var(--r-md)] bg-[var(--brand-500)] text-white">
            <Sparkles className="h-4 w-4" />
          </span>
          <p className="min-w-0 flex-1 truncate text-sm font-semibold">{meta.destination}</p>
          {state && (
            <Button size="sm" loading={saving} onClick={() => void saveToMyTrips()}>
              <Plus className="h-4 w-4" />
              Save to my trips
            </Button>
          )}
        </div>
      </header>

      {error ? (
        <div className="mx-auto max-w-5xl px-4 py-16">
          <div className="surface-card p-8 text-center text-sm text-[var(--muted)]">{error}</div>
        </div>
      ) : !state ? (
        <div className="grid place-items-center py-24">
          <Spinner className="h-6 w-6 text-[var(--brand-500)]" />
        </div>
      ) : (
        <>
          {/* Hero — the trip at a glance, like the offline pass cover. */}
          <div className="relative overflow-hidden bg-gradient-to-br from-[var(--brand-600)] to-[var(--brand-400)] text-white">
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 opacity-25"
              style={{ backgroundImage: "radial-gradient(circle at 85% 15%, rgba(255,255,255,0.5) 0, transparent 45%)" }}
            />
            <div className="relative mx-auto max-w-5xl px-4 pb-14 pt-8 sm:pb-16 sm:pt-10">
              <p className="text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-white/80">Your trip itinerary</p>
              <h1 className="mt-1 font-[family-name:var(--font-display)] text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
                {meta.destination}
              </h1>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-sm text-white/90">
                {dateLabel && <span className="inline-flex items-center gap-1.5"><Calendar className="h-4 w-4" />{dateLabel}</span>}
                {byDay.length > 0 && <span className="inline-flex items-center gap-1.5"><Clock className="h-4 w-4" />{byDay.length} days</span>}
                {meta.travellers && <span className="inline-flex items-center gap-1.5"><Users2 className="h-4 w-4" />{meta.travellers} travelling</span>}
                {meta.budgetTotal != null && (
                  <span className="inline-flex items-center gap-1.5"><Wallet className="h-4 w-4" />{meta.budgetCurrency} {Math.round(meta.budgetTotal).toLocaleString()}</span>
                )}
              </div>
              {meta.overview && <p className="mt-4 max-w-2xl text-sm leading-relaxed text-white/85">{meta.overview}</p>}
            </div>
          </div>

          <main className="mx-auto -mt-8 w-full max-w-5xl px-4 pb-16">
            {token && (
              <div className="mb-6">
                <GroupVote token={token} results={state.results} />
              </div>
            )}

            {/* Day-by-day itinerary — the clearest thing on the page. */}
            {byDay.length > 0 && (
              <section className="mb-10 rounded-[var(--r-xl)] border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-1)] sm:p-6">
                <h2 className="mb-4 flex items-center gap-2 font-[family-name:var(--font-display)] text-xl font-bold tracking-tight">
                  <Calendar className="h-5 w-5 text-[var(--brand-500)]" />
                  Day-by-day
                </h2>
                <div className="space-y-6">
                  {byDay.map(([day, items]) => (
                    <div key={day}>
                      <div className="mb-3 flex items-center gap-3">
                        <span className="inline-flex items-center rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--brand-400)_18%,transparent)] px-3 py-1 text-sm font-bold text-[var(--brand-600)]">
                          Day {day}
                        </span>
                        {dayDate(meta.start, day) && <span className="text-xs font-medium text-[var(--muted)]">{dayDate(meta.start, day)}</span>}
                      </div>
                      <ol className="relative space-y-2.5 border-l border-[var(--border)] pl-4">
                        {items
                          .slice()
                          .sort((a, b) => String(a.starts_at ?? "").localeCompare(String(b.starts_at ?? "")))
                          .map((it, i) => {
                            const Icon = KIND_ICON[String(it.kind)] ?? Compass;
                            const loc = (it.details as Record<string, unknown> | undefined)?.location
                              ?? (it.details as Record<string, unknown> | undefined)?.address
                              ?? (it.details as Record<string, unknown> | undefined)?.area;
                            const cost = it.cost_amount ? `${it.cost_currency ?? ""} ${Math.round(Number(it.cost_amount)).toLocaleString()}`.trim() : "";
                            const isPlace = ["activity", "meal", "restaurant", "hotel"].includes(String(it.kind));
                            const href = mapsSearchUrl(it.title, meta.destination);
                            return (
                              <li key={i} className="relative">
                                <span className="absolute -left-[1.36rem] top-1 grid h-5 w-5 place-items-center rounded-full bg-[var(--brand-500)] text-white ring-4 ring-[var(--surface)]">
                                  <Icon className="h-3 w-3" weight="fill" />
                                </span>
                                <div className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--bg)] p-2.5">
                                  <div className="flex gap-3">
                                    {isPlace && (
                                      <a
                                        href={href}
                                        target="_blank"
                                        rel="noreferrer noopener"
                                        aria-label={`See ${it.title} on the map`}
                                        className="relative block h-16 w-16 shrink-0 overflow-hidden rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)]"
                                      >
                                        <PlaceImage
                                          query={it.title}
                                          city={meta.destination}
                                          alt={it.title}
                                          className="h-full w-full object-cover"
                                          fallback={<span className="grid h-full w-full place-items-center text-[var(--brand-500)]"><Icon className="h-6 w-6" weight="fill" /></span>}
                                        />
                                      </a>
                                    )}
                                    <div className="min-w-0 flex-1">
                                      <div className="flex items-start justify-between gap-2">
                                        <a
                                          href={href}
                                          target="_blank"
                                          rel="noreferrer noopener"
                                          className="group inline-flex items-start gap-1 text-sm font-semibold leading-snug hover:text-[var(--brand-600)]"
                                        >
                                          <span className="min-w-0">{it.title}</span>
                                          <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-[var(--muted)] transition-colors group-hover:text-[var(--brand-600)]" />
                                        </a>
                                        {it.starts_at && (
                                          <span className="shrink-0 rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)] px-2 py-0.5 text-[0.7rem] font-semibold tabular-nums text-[var(--brand-600)]">
                                            {it.starts_at}{it.ends_at ? `–${it.ends_at}` : ""}
                                          </span>
                                        )}
                                      </div>
                                      <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[0.7rem] text-[var(--muted)]">
                                        <span className="font-medium">{KIND_LABEL[String(it.kind)] ?? "Stop"}</span>
                                        {loc ? <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{String(loc)}</span> : null}
                                        {cost ? <span className="font-medium text-[var(--text)]">{cost}</span> : null}
                                      </div>
                                      {it.reasoning && <p className="mt-1 text-xs leading-relaxed text-[var(--muted)]">{it.reasoning}</p>}
                                    </div>
                                  </div>
                                </div>
                              </li>
                            );
                          })}
                      </ol>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Flights, stays, places to visit / eat, and the rest. */}
            <TripExtraPanels results={state.results} />

            <p className="mt-10 text-center text-xs text-[var(--muted)]">
              Prepared with <span className="font-semibold text-[var(--brand-600)]">Journava</span> — travel, planned by agents.
            </p>
          </main>
        </>
      )}
    </div>
  );
}
