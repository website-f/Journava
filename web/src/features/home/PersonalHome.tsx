import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "framer-motion";
import {
  Plane,
  Briefcase,
  Compass,
  FileCheck2,
  Clock,
  ArrowRight,
  Sparkles,
  X,
} from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { Page, SectionHeader } from "@/components/layout/Page";
import { useIsMobile } from "@/hooks/useMediaQuery";
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
  similar: Compass,
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
  const [showAll, setShowAll] = useState(false);

  const { data } = useQuery({
    queryKey: ["recommendations"],
    queryFn: () => api.get<{ recommendations: Recommendation[] }>("/recommendations?limit=12"),
    staleTime: 60_000,
  });
  const recommendations = data?.recommendations ?? [];

  const firstName = (user?.display_name ?? "traveller").split(" ")[0];
  const tripScope = activeTrip?._scope as ScopeMeta | undefined;

  return (
    <Page width="lg" className="space-y-7">
      {/* The greeting is the app's face: oversized display type, the name on its
          own line. A small "Good morning," over a 2xl name read like a dashboard
          label; this reads like an app that knows who opened it. */}
      <header>
        <p className="text-[0.8125rem] font-semibold uppercase tracking-[0.14em] text-[var(--muted)]">
          {timeGreeting()}
        </p>
        <h1 className="mt-1 font-[family-name:var(--font-display)] text-[2.25rem] font-bold leading-[1.05] tracking-[-0.03em] sm:text-[2.75rem]">
          {firstName}
        </h1>
        <p className="mt-2.5 max-w-[42ch] text-sm leading-relaxed text-[var(--muted)]">
          Tell your agents what you want — they plan, research and book it while you watch.
        </p>
      </header>

      {activeTrip && (
        <button
          onClick={() => navigate("/trip")}
          className="pressable flex w-full items-center gap-4 overflow-hidden rounded-[var(--r-xl)] bg-[var(--brand-600)] p-4 text-left text-white shadow-[var(--shadow-2)]"
        >
          <span className="grid h-12 w-12 shrink-0 place-items-center rounded-[var(--r-md)] bg-white/12 ring-1 ring-inset ring-white/20">
            <Briefcase className="h-5 w-5" weight="fill" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[0.65rem] font-bold uppercase tracking-[0.14em] text-[var(--accent)]">
              Your active trip
            </span>
            <span className="mt-0.5 block truncate font-[family-name:var(--font-display)] text-[1.0625rem] font-semibold">
              {tripScope?.label ?? "Continue planning"}
            </span>
          </span>
          <ArrowRight className="h-5 w-5 shrink-0 text-white/70" />
        </button>
      )}

      <section>
        <SectionHeader
          icon={<Sparkles className="h-[1.15rem] w-[1.15rem] text-[var(--accent)]" weight="fill" />}
          title="For you"
          hint="Drawn from your own trips and searches — not a generic featured list."
          action={
            recommendations.length > 3 && (
              <button
                onClick={() => setShowAll(true)}
                className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--brand-600)] hover:underline"
              >
                See all {recommendations.length}
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
            )
          }
        />
        <div className="grid gap-3 sm:grid-cols-2">
          {recommendations.slice(0, 4).map((rec, index) => (
            <RecCard key={rec.id ?? `${rec.scope}-${index}`} rec={rec} onLaunch={onLaunch} />
          ))}
        </div>
      </section>

      {showAll && (
        <SuggestionsDrawer
          recs={recommendations}
          onClose={() => setShowAll(false)}
          onLaunch={(scope, goal) => {
            setShowAll(false);
            onLaunch(scope, goal);
          }}
        />
      )}
    </Page>
  );
}

function RecCard({
  rec,
  onLaunch,
}: {
  rec: Recommendation;
  onLaunch: (scope: string, goal?: string) => void;
}) {
  const Icon = ICONS[rec.icon ?? ""] ?? Sparkles;
  return (
    <button
      onClick={() => onLaunch(rec.scope, rec.goal)}
      className="surface-card pressable group flex w-full items-start gap-3 p-4 text-left hover:border-[var(--brand-400)] hover:shadow-[var(--shadow-2)]"
    >
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[var(--r-md)] bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)] text-[var(--brand-600)]">
        <Icon className="h-5 w-5" weight="fill" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.9375rem] font-semibold leading-snug tracking-[-0.01em]">
          {rec.title}
        </span>
        <span className="mt-1 block text-xs leading-relaxed text-[var(--muted)]">{rec.subtitle}</span>
      </span>
      {/* The chevron always shows: on touch there is no hover to reveal it, and
          it's the only thing saying the card is tappable. */}
      <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-[var(--muted)] transition-transform duration-[var(--dur)] group-hover:translate-x-0.5 group-hover:text-[var(--brand-600)]" />
    </button>
  );
}

/**
 * The full suggestion list — recents, agent picks and "similar to your last trip".
 *
 * A bottom sheet on phones and a side panel from `sm` up. A right-hand offcanvas
 * on a phone is a desktop pattern: it arrives from the edge furthest from your
 * thumb, and the close button ends up in the top corner you can't reach.
 */
function SuggestionsDrawer({
  recs,
  onLaunch,
  onClose,
}: {
  recs: Recommendation[];
  onLaunch: (scope: string, goal?: string) => void;
  onClose: () => void;
}) {
  const isMobile = useIsMobile();

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay asChild>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="fixed inset-0 z-[85] bg-black/50 backdrop-blur-sm"
          />
        </Dialog.Overlay>
        <Dialog.Content asChild>
          <motion.div
            initial={isMobile ? { y: "100%" } : { x: "100%" }}
            animate={isMobile ? { y: 0 } : { x: 0 }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
            className={cn(
              "fixed z-[86] flex flex-col bg-[var(--elevated)] shadow-[var(--shadow-3)]",
              "inset-x-0 bottom-0 max-h-[85dvh] rounded-t-[var(--r-xl)] border-t border-[var(--border)]",
              "sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-[min(28rem,100%)]",
              "sm:rounded-none sm:border-t-0 sm:border-l",
            )}
          >
            {/* Grab handle — the affordance that says "this sheet came from the
                bottom edge and goes back there". Phones only. */}
            <span
              aria-hidden
              className="mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-[var(--border)] sm:hidden"
            />
            <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] p-4">
              <div className="min-w-0">
                <Dialog.Title className="font-[family-name:var(--font-display)] text-[1.125rem] font-bold tracking-[-0.02em]">
                  Suggestions for you
                </Dialog.Title>
                <Dialog.Description className="mt-0.5 text-xs leading-relaxed text-[var(--muted)]">
                  From your past trips, searches, and places with a similar vibe.
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <button
                  aria-label="Close"
                  data-fixed-size
                  className="tap-target grid h-9 w-9 shrink-0 place-items-center rounded-full text-[var(--muted)] hover:bg-[var(--surface)] hover:text-[var(--text)]"
                >
                  <X className="h-4 w-4" />
                </button>
              </Dialog.Close>
            </div>
            <div
              className="min-h-0 flex-1 space-y-2.5 overflow-y-auto overscroll-contain p-4"
              style={{ paddingBottom: "calc(1rem + var(--safe-bottom))" }}
            >
              {recs.map((rec, index) => (
                <RecCard key={rec.id ?? `${rec.scope}-${index}`} rec={rec} onLaunch={onLaunch} />
              ))}
            </div>
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
