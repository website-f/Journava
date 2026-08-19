import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Plane,
  Briefcase,
  Compass,
  FileCheck2,
  Clock,
  ArrowRight,
  Sparkles,
} from "@/components/ui/icons";
import { api } from "@/lib/api";
import { useAuth } from "@/providers/AuthProvider";
import { usePlanStore } from "@/stores/planStore";
import type { ScopeMeta } from "@/lib/types";

type Recommendation = {
  id?: string;
  kind: string;
  title: string;
  subtitle: string;
  scope: string;
  goal?: string;
  icon?: string;
};

const ICONS: Record<string, typeof Plane> = {
  flight: Plane,
  trip: Briefcase,
  explore: Compass,
  visa: FileCheck2,
  history: Clock,
};

function timeGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/**
 * Personalized home (spec §3.1) — the landing surface before a scope is chosen.
 * Greets the signed-in traveller, resurfaces their active trip, and offers
 * "for you" cards derived from their own history (see /recommendations).
 */
export function PersonalHome({
  onLaunch,
}: {
  onLaunch: (scope: string, goal?: string) => void;
}) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const activeTrip = usePlanStore((s) => s.byScope["full_trip"] ?? null);

  const { data } = useQuery({
    queryKey: ["recommendations"],
    queryFn: () => api.get<{ recommendations: Recommendation[] }>("/recommendations"),
    staleTime: 60_000,
  });
  const recommendations = data?.recommendations ?? [];

  const firstName = (user?.display_name ?? "traveller").split(" ")[0];
  const tripScope = activeTrip?._scope as ScopeMeta | undefined;

  return (
    <section className="mx-auto w-full max-w-5xl space-y-7">
      <header>
        <p className="text-sm text-[var(--muted)]">{timeGreeting()},</p>
        <h1 className="font-[family-name:var(--font-display)] text-2xl sm:text-3xl mt-0.5">
          {firstName}
        </h1>
        <p className="mt-1.5 text-sm text-[var(--muted)] max-w-prose">
          Tell your agents what you want — they plan, research and book it while you watch.
        </p>
      </header>

      {activeTrip && (
        <button
          onClick={() => navigate("/trip")}
          className="surface-card w-full p-4 flex items-center gap-4 text-left transition-colors hover:border-[var(--brand-400)]"
        >
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)] text-[var(--brand-500)]">
            <Briefcase className="h-5 w-5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[0.7rem] font-semibold uppercase tracking-wide text-[var(--muted)]">
              Your active trip
            </span>
            <span className="block font-medium truncate">
              {tripScope?.label ?? "Continue planning"}
            </span>
          </span>
          <ArrowRight className="h-4 w-4 shrink-0 text-[var(--muted)]" />
        </button>
      )}

      <div>
        <h2 className="mb-2.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
          <Sparkles className="h-3.5 w-3.5 text-[var(--accent)]" /> For you
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {recommendations.map((rec, index) => {
            const Icon = ICONS[rec.icon ?? ""] ?? Sparkles;
            return (
              <button
                key={rec.id ?? `${rec.scope}-${index}`}
                onClick={() => onLaunch(rec.scope, rec.goal)}
                className="surface-card group flex items-start gap-3 p-4 text-left transition-colors hover:border-[var(--brand-400)]"
              >
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)] text-[var(--brand-500)]">
                  <Icon className="h-5 w-5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium leading-snug">{rec.title}</span>
                  <span className="mt-0.5 block text-xs text-[var(--muted)]">{rec.subtitle}</span>
                </span>
                <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-[var(--muted)] opacity-0 transition-opacity group-hover:opacity-100" />
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
