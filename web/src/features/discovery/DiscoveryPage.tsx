import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Compass, Camera, Video, Newspaper, Globe, Share, Sparkles, Trash2 } from "@/components/ui/icons";
import type { IconType } from "@/components/ui/icons";
import { EmptyState, Skeleton } from "@/components/ui";
import { Page, PageHeader } from "@/components/layout/Page";
import { api } from "@/lib/api";

type Link = { type: string; title: string; url: string };
type Discovery = {
  id: string; image_url: string | null; title: string; category: string | null;
  description: string | null; facts: string[]; links: Link[]; created_at: string | null;
};

const LINK_ICON: Record<string, IconType> = { video: Video, social: Share, news: Newspaper, web: Globe };
const CAT_TONE: Record<string, string> = {
  place: "var(--brand-500)", landmark: "var(--brand-500)", food: "var(--accent)", drink: "var(--accent)",
  nature: "var(--success)", animal: "var(--success)", art: "var(--warm)", object: "var(--muted)",
};

/**
 * Discovery — the traveller's saved visual-search notes. Each card is something
 * they snapped with the AI camera (assistant → + → AI Camera): what it is, a few
 * facts, and the watch/read/explore links the vision + Camofox pass surfaced.
 */
export function DiscoveryPage() {
  const [items, setItems] = useState<Discovery[] | null>(null);

  const load = () => {
    api.get<{ discoveries: Discovery[] }>("/discoveries").then((r) => setItems(r.discoveries)).catch(() => setItems([]));
  };
  useEffect(() => { load(); }, []);

  const del = async (id: string) => {
    setItems((xs) => (xs ? xs.filter((x) => x.id !== id) : xs));
    try { await api.del(`/discoveries/${id}`); }
    catch { toast.error("Couldn't remove that."); load(); }
  };

  return (
    <Page width="xl">
      <PageHeader
        eyebrow="Travel notes"
        title="Discovery"
        subtitle="Everything you've pointed the AI camera at — places, food, landmarks — with the reviews and clips to go deeper."
      />

      <div className="mb-5 flex items-center gap-2 rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm text-[var(--muted)]">
        <Camera className="h-5 w-5 shrink-0 text-[var(--brand-500)]" weight="duotone" />
        Open the assistant, tap <strong className="mx-1 text-[var(--text)]">+ → AI Camera</strong>, and snap a place or dish to add it here.
      </div>

      {items === null ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-64 w-full rounded-[var(--r-lg)]" />)}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Compass className="h-8 w-8" />}
          title="No discoveries yet"
          description="Snap a landmark, a dish or a shopfront with the AI camera and it lands here as a travel note."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((d) => (
            <article key={d.id} className="surface-card group flex flex-col overflow-hidden p-0">
              {d.image_url && (
                <div className="relative h-40 w-full overflow-hidden bg-[var(--bg)]">
                  <img src={d.image_url} alt={d.title} className="h-full w-full object-cover" />
                  {d.category && (
                    <span className="absolute left-2 top-2 rounded-[var(--r-pill)] px-2 py-0.5 text-[0.6rem] font-semibold uppercase text-white" style={{ background: CAT_TONE[d.category] ?? "var(--muted)" }}>
                      {d.category}
                    </span>
                  )}
                  <button onClick={() => void del(d.id)} aria-label="Remove" className="absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-full bg-black/50 text-white opacity-0 transition-opacity group-hover:opacity-100">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
              <div className="flex min-w-0 flex-1 flex-col p-4">
                <h3 className="font-[family-name:var(--font-display)] text-lg font-bold tracking-tight">{d.title}</h3>
                {d.description && <p className="mt-1 text-sm text-[var(--muted)]">{d.description}</p>}
                {d.facts.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {d.facts.slice(0, 3).map((f, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-xs"><Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-[var(--accent)]" /> {f}</li>
                    ))}
                  </ul>
                )}
                {d.links.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {d.links.slice(0, 5).map((l, i) => {
                      const Icon = LINK_ICON[l.type] ?? Globe;
                      return (
                        <a key={i} href={l.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 rounded-[var(--r-pill)] border border-[var(--border)] bg-[var(--bg)] px-2 py-0.5 text-[0.7rem] hover:border-[var(--brand-400)]">
                          <Icon className="h-3 w-3 text-[var(--brand-500)]" /> {l.title}
                        </a>
                      );
                    })}
                  </div>
                )}
                {d.created_at && <p className="mt-auto pt-3 text-[0.65rem] text-[var(--muted)]">{d.created_at.slice(0, 10)}</p>}
              </div>
            </article>
          ))}
        </div>
      )}
    </Page>
  );
}
