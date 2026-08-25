import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { motion } from "framer-motion";
import { Briefcase, ArrowRight, Sparkles, X, Compass } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
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
  image?: string | null;
  destination?: string;
};

function timeGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/**
 * Home top: greeting, a "your plan is ready" banner (post-notification), and the
 * active-trip shortcut. The scope picker and the "for you" discovery grid render
 * below this (see CommandCenter), so the fastest paths in come first.
 */
export function PersonalHome() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const activeTrip = usePlanStore((s) => s.byScope["full_trip"] ?? null);
  const firstName = (user?.display_name ?? "traveller").split(" ")[0];
  const tripScope = activeTrip?._scope as ScopeMeta | undefined;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5">
      <PlanReadyBanner />

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
    </div>
  );
}

type ReadyTrip = { id?: string; destination?: string; goal?: string } | null;

/**
 * "Your full trip is ready to view." A background full-trip run finishes and pings
 * the traveller (Telegram/email); when they open the app this surfaces the most
 * recent completed plan at the top of home so they don't have to dig through
 * History. Dismisses once viewed (per-plan, in localStorage) and re-appears for
 * the next completed trip.
 */
function PlanReadyBanner() {
  const navigate = useNavigate();
  const [trip, setTrip] = useState<ReadyTrip>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<{ ready: ReadyTrip }>("/trip/ready")
      .then((res) => {
        const r = res?.ready;
        if (cancelled || !r?.id) return;
        let dismissed = "";
        try {
          dismissed = localStorage.getItem("journava:trip-viewed") ?? "";
        } catch {
          /* private mode */
        }
        if (dismissed !== r.id) setTrip(r);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!trip?.id) return null;
  const label = trip.destination || trip.goal || "your trip";

  const view = () => {
    try {
      localStorage.setItem("journava:trip-viewed", trip.id ?? "");
    } catch {
      /* private mode */
    }
    setTrip(null);
    navigate("/trip?tab=history");
  };

  return (
    <motion.button
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      onClick={view}
      className="pressable flex w-full items-center gap-3 rounded-[var(--r-lg)] border border-[var(--success)]/40 bg-[color-mix(in_srgb,var(--success)_12%,transparent)] p-4 text-left"
    >
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[var(--success)] text-white">
        <Sparkles className="h-5 w-5" weight="fill" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold text-[var(--text)]">
          Your trip to {label} is ready to view
        </span>
        <span className="block text-xs text-[var(--muted)]">Your agents finished planning — tap to open it.</span>
      </span>
      <ArrowRight className="h-5 w-5 shrink-0 text-[var(--success)]" />
    </motion.button>
  );
}

/**
 * Discovery-first "For you": destinations the traveller hasn't searched yet
 * (similar-to-their-trips + iconic places), each with a photo thumbnail. Renders
 * at the BOTTOM of home so the ask-surfaces lead.
 */
export function ForYou({ onLaunch }: { onLaunch: (scope: string, goal?: string) => void }) {
  const [showAll, setShowAll] = useState(false);
  const { data } = useQuery({
    queryKey: ["recommendations"],
    queryFn: () => api.get<{ recommendations: Recommendation[] }>("/recommendations?limit=12"),
    staleTime: 60_000,
  });
  const recs = data?.recommendations ?? [];
  if (recs.length === 0) return null;

  return (
    <section className="mx-auto w-full max-w-5xl">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
          <Sparkles className="h-4 w-4 text-[var(--accent)]" weight="fill" /> For you
        </h3>
        {recs.length > 4 && (
          <button
            onClick={() => setShowAll(true)}
            className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--brand-600)] hover:underline"
          >
            See all {recs.length} <ArrowRight className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {recs.slice(0, 8).map((rec, i) => (
          <RecCard key={rec.id ?? `${rec.scope}-${i}`} rec={rec} onLaunch={onLaunch} />
        ))}
      </div>
      {showAll && (
        <SuggestionsDrawer
          recs={recs}
          onClose={() => setShowAll(false)}
          onLaunch={(scope, goal) => {
            setShowAll(false);
            onLaunch(scope, goal);
          }}
        />
      )}
    </section>
  );
}

function RecCard({ rec, onLaunch }: { rec: Recommendation; onLaunch: (scope: string, goal?: string) => void }) {
  return (
    <button
      onClick={() => onLaunch(rec.scope, rec.goal)}
      className="surface-card pressable group flex flex-col overflow-hidden p-0 text-left hover:border-[var(--brand-400)] hover:shadow-[var(--shadow-2)]"
    >
      <div className="relative h-24 w-full overflow-hidden bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)]">
        {rec.image ? (
          <img src={rec.image} alt={rec.title} loading="lazy" className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105" />
        ) : (
          <span className="grid h-full w-full place-items-center text-[var(--brand-500)]">
            <Compass className="h-7 w-7" />
          </span>
        )}
      </div>
      <div className="min-w-0 p-3">
        <span className="block truncate text-sm font-semibold leading-snug">{rec.title}</span>
        <span className="mt-0.5 block line-clamp-2 text-[0.7rem] leading-snug text-[var(--muted)]">{rec.subtitle}</span>
      </div>
    </button>
  );
}

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
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="fixed inset-0 z-[85] bg-black/50 backdrop-blur-sm" />
        </Dialog.Overlay>
        <Dialog.Content asChild>
          <motion.div
            initial={isMobile ? { y: "100%" } : { x: "100%" }}
            animate={isMobile ? { y: 0 } : { x: 0 }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
            className={cn(
              "fixed z-[86] flex flex-col bg-[var(--elevated)] shadow-[var(--shadow-3)]",
              "inset-x-0 bottom-0 max-h-[85dvh] rounded-t-[var(--r-xl)] border-t border-[var(--border)]",
              "sm:inset-y-0 sm:left-auto sm:right-0 sm:max-h-none sm:w-[min(30rem,100%)]",
              "sm:rounded-none sm:border-t-0 sm:border-l",
            )}
          >
            <span aria-hidden className="mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-[var(--border)] sm:hidden" />
            <div className="flex items-start justify-between gap-3 border-b border-[var(--border)] p-4">
              <div className="min-w-0">
                <Dialog.Title className="font-[family-name:var(--font-display)] text-[1.125rem] font-bold tracking-[-0.02em]">
                  Where to next
                </Dialog.Title>
                <Dialog.Description className="mt-0.5 text-xs leading-relaxed text-[var(--muted)]">
                  Destinations with a similar vibe to your trips — that you haven&rsquo;t explored yet.
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <button aria-label="Close" data-fixed-size className="tap-target grid h-9 w-9 shrink-0 place-items-center rounded-full text-[var(--muted)] hover:bg-[var(--surface)] hover:text-[var(--text)]">
                  <X className="h-4 w-4" />
                </button>
              </Dialog.Close>
            </div>
            <div className="grid min-h-0 flex-1 grid-cols-2 gap-3 overflow-y-auto overscroll-contain p-4" style={{ paddingBottom: "calc(1rem + var(--safe-bottom))" }}>
              {recs.map((rec, i) => (
                <RecCard key={rec.id ?? `${rec.scope}-${i}`} rec={rec} onLaunch={onLaunch} />
              ))}
            </div>
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
