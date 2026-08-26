import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { MapTrifold, Sparkles, CheckCircle2, Loader2, ArrowRight } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";

type Page = { found: boolean; org_name?: string; headline?: string; subhead?: string };
type Phase = "form" | "building" | "ready" | "closed" | "error";

/**
 * Public Package Builder page (no account). A prospective client describes the
 * trip they want; the agency's 21-agent mesh auto-drafts a full package while
 * they watch, and they open the finished plan at the end. The agency gets the
 * lead with the package attached. Rendered at /p/:token, before the auth wall.
 */
export function PackageRequest() {
  const { token = "" } = useParams();
  const [page, setPage] = useState<Page | null>(null);
  const [phase, setPhase] = useState<Phase>("form");
  const [shareToken, setShareToken] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", contact: "", destination: "", budget: "", dates: "", travellers: 2 });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api.get<Page>(`/packages/${token}`).then(setPage).catch(() => setPage({ found: false }));
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [token]);

  const submit = async () => {
    if (!form.name.trim() || !form.destination.trim()) return;
    setPhase("building");
    try {
      const res = await api.post<{ job_id: string }>(`/packages/${token}/request`, form);
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.get<{ status: string; share_token?: string }>(`/packages/job/${res.job_id}`);
          if (s.status === "done" && s.share_token) {
            if (pollRef.current) clearInterval(pollRef.current);
            setShareToken(s.share_token);
            setPhase("ready");
          } else if (s.status === "error") {
            if (pollRef.current) clearInterval(pollRef.current);
            setPhase("error");
          }
        } catch {
          /* keep polling */
        }
      }, 3000);
    } catch {
      setPhase("error");
    }
  };

  if (page === null) {
    return <Centered><Loader2 className="h-6 w-6 animate-spin text-[var(--brand-500)]" /></Centered>;
  }
  if (!page.found) {
    return (
      <Centered>
        <p className="text-lg font-semibold">This planning page isn&rsquo;t available.</p>
        <p className="text-sm text-[var(--muted)]">Ask your travel agent for a fresh link.</p>
      </Centered>
    );
  }

  return (
    <div className="min-h-[100dvh] bg-[var(--bg)] text-[var(--text)]">
      <div className="mx-auto w-full max-w-lg px-4 py-10">
        <div className="mb-6 flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-[var(--r-md)] bg-[var(--brand-500)] text-white">
            <MapTrifold className="h-5 w-5" weight="fill" />
          </span>
          <span className="text-sm font-semibold">{page.org_name}</span>
        </div>

        <h1 className="font-[family-name:var(--font-display)] text-[2rem] font-bold leading-tight tracking-tight">
          {page.headline}
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">{page.subhead}</p>

        {phase === "form" && (
          <div className="mt-6 space-y-3">
            <Field label="Your name">
              <input className={INPUT} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Jane Traveller" />
            </Field>
            <Field label="Email or WhatsApp">
              <input className={INPUT} value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} placeholder="so we can send your package" />
            </Field>
            <Field label="Where do you want to go?">
              <input className={INPUT} value={form.destination} onChange={(e) => setForm({ ...form, destination: e.target.value })} placeholder="e.g. Bali, Istanbul, Kyoto" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Budget (optional)">
                <input className={INPUT} value={form.budget} onChange={(e) => setForm({ ...form, budget: e.target.value })} placeholder="RM 8,000" />
              </Field>
              <Field label="Travellers">
                <input type="number" min={1} className={INPUT} value={form.travellers} onChange={(e) => setForm({ ...form, travellers: Number(e.target.value) || 1 })} />
              </Field>
            </div>
            <Field label="When (optional)">
              <input className={INPUT} value={form.dates} onChange={(e) => setForm({ ...form, dates: e.target.value })} placeholder="next December, 5 days" />
            </Field>
            <Button className="w-full" onClick={() => void submit()} disabled={!form.name.trim() || !form.destination.trim()}>
              <Sparkles className="h-4 w-4" /> Build my package
            </Button>
            <p className="text-center text-[0.7rem] text-[var(--muted)]">
              Our AI travel designer drafts a full itinerary, flights, stays and budget — in minutes.
            </p>
          </div>
        )}

        {phase === "building" && (
          <div className="mt-8 grid place-items-center gap-4 rounded-[var(--r-xl)] border border-[var(--border)] p-8 text-center">
            <span className="relative grid h-16 w-16 place-items-center">
              <span className="absolute inset-0 animate-ping rounded-full bg-[var(--brand-400)]/40" />
              <span className="grid h-16 w-16 place-items-center rounded-full bg-[var(--brand-500)] text-white">
                <Sparkles className="h-7 w-7" weight="fill" />
              </span>
            </span>
            <p className="text-lg font-semibold">Designing your trip to {form.destination}…</p>
            <p className="max-w-xs text-sm text-[var(--muted)]">
              {page.org_name}&rsquo;s AI agents are researching flights, stays, places and budget for you. This takes a minute.
            </p>
          </div>
        )}

        {phase === "ready" && shareToken && (
          <div className="mt-8 grid place-items-center gap-4 rounded-[var(--r-xl)] border border-[var(--success)]/40 bg-[color-mix(in_srgb,var(--success)_8%,transparent)] p-8 text-center">
            <CheckCircle2 className="h-12 w-12 text-[var(--success)]" weight="fill" />
            <p className="text-lg font-semibold">Your package is ready!</p>
            <p className="max-w-xs text-sm text-[var(--muted)]">
              {page.org_name} will follow up with you — meanwhile, explore the plan our agents drafted.
            </p>
            <Button asChild className="w-full">
              <a href={`/s/${shareToken}`}>View my package <ArrowRight className="h-4 w-4" /></a>
            </Button>
          </div>
        )}

        {phase === "error" && (
          <div className="mt-8 rounded-[var(--r-lg)] border border-[var(--border)] p-6 text-center">
            <p className="font-semibold">Something interrupted the build.</p>
            <p className="mt-1 text-sm text-[var(--muted)]">Please try again in a moment.</p>
            <Button variant="secondary" className="mt-3" onClick={() => setPhase("form")}>Try again</Button>
          </div>
        )}
      </div>
    </div>
  );
}

const INPUT =
  "w-full rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5 text-sm";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--muted)]">{label}</span>
      {children}
    </label>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="grid min-h-[100dvh] place-items-center gap-2 bg-[var(--bg)] px-6 text-center">{children}</div>;
}
