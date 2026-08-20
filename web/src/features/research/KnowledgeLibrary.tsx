import { useQuery } from "@tanstack/react-query";
import {
  BadgeCheck,
  Building2,
  Bus,
  Cloud,
  Compass,
  FileCheck2,
  Plane,
  ShieldAlert,
  TrendingUp,
  Utensils,
} from "@/components/ui/icons";
import { Badge, EmptyState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

/**
 * Knowledge library — the findings the agents document from every plan, grouped
 * by category and written up like short articles ("Hotel prices in Tokyo…",
 * "Entry rules for Australia…"). It grows with each trip, and the agents read it
 * back to plan smarter next time.
 */

interface Note {
  id: string;
  category: string;
  destination?: string | null;
  title: string;
  body: string;
  tags: string[];
  confidence: string;
  source?: string | null;
  seen_count: number;
  updated_at?: string | null;
}

const CAT_META: Record<string, { label: string; icon: typeof Plane }> = {
  flights: { label: "Flights", icon: Plane },
  hotels: { label: "Hotels & stays", icon: Building2 },
  food: { label: "Food", icon: Utensils },
  activities: { label: "Places to visit", icon: Compass },
  visa: { label: "Visa & entry", icon: FileCheck2 },
  weather: { label: "Weather", icon: Cloud },
  safety: { label: "Safety", icon: ShieldAlert },
  budget: { label: "Budget", icon: TrendingUp },
  transport: { label: "Transport", icon: Bus },
  general: { label: "General", icon: BadgeCheck },
};

export function KnowledgeLibrary() {
  const { data, isLoading } = useQuery({
    queryKey: ["knowledge"],
    queryFn: () =>
      api.get<{ grouped: Record<string, Note[]>; categories: string[] }>("/knowledge"),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div className="grid gap-3 py-3 sm:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      </div>
    );
  }

  const grouped = data?.grouped ?? {};
  const categories = Object.keys(grouped);

  if (categories.length === 0) {
    return (
      <div className="py-10">
        <EmptyState
          icon={<BadgeCheck className="h-10 w-10" />}
          title="No findings yet"
          description="As your agents research trips, what they learn — hotel price ranges, visa rules, the best places to eat — gets documented here as a growing library."
        />
      </div>
    );
  }

  return (
    <div className="space-y-6 py-3">
      <p className="text-sm text-[var(--muted)]">
        Everything your agents have learned, documented and grouped. Every plan adds to it —
        and reads from it to plan smarter next time.
      </p>
      {categories.map((cat) => {
        const meta = CAT_META[cat] ?? { label: cat, icon: BadgeCheck };
        const Icon = meta.icon;
        return (
          <section key={cat}>
            <h3 className="mb-2 flex items-center gap-2 text-lg font-semibold">
              <Icon className="h-5 w-5 text-[var(--brand-500)]" />
              {meta.label}
              <Badge variant="brand">{grouped[cat].length}</Badge>
            </h3>
            <div className="grid gap-3 sm:grid-cols-2">
              {grouped[cat].map((note) => (
                <NoteCard key={note.id} note={note} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function NoteCard({ note }: { note: Note }) {
  return (
    <article className="surface-card flex flex-col p-4">
      <div className="flex items-start justify-between gap-2">
        <h4 className="min-w-0 text-sm font-semibold">{note.title}</h4>
        {note.destination && <Badge>{note.destination}</Badge>}
      </div>
      <p className="mt-1.5 flex-1 text-xs leading-relaxed text-[var(--muted)]">{note.body}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.6rem] text-[var(--muted)]">
        {note.source && <span>via {note.source}</span>}
        {note.seen_count > 1 && <span>· confirmed {note.seen_count}×</span>}
        {note.tags.slice(0, 2).map((t) => (
          <span key={t} className="rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)] px-1.5 py-0.5">
            {t}
          </span>
        ))}
      </div>
    </article>
  );
}
