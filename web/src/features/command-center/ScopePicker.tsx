import { motion } from "framer-motion";
import {
  Building2,
  Bus,
  Calendar,
  Cloud,
  Compass,
  Plane,
  Sparkles,
  Utensils,
  Wallet,
  type IconType,
} from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui";
import type { Scope } from "@/lib/types";

/**
 * The Command Center home screen: pick what you want before you ask for it.
 *
 * Scoping the question up front is what keeps the answer proportionate. Asking
 * for flights used to wake all 21 agents and bury three fares under visa rules
 * and carbon estimates; choosing "Flights only" runs three agents and answers
 * the question that was actually asked.
 *
 * Each card states its agent count and rough duration, so the cost of a choice
 * is visible before it is made.
 */

const ICONS: Record<string, IconType> = {
  sparkles: Sparkles,
  plane: Plane,
  utensils: Utensils,
  building: Building2,
  compass: Compass,
  cloud: Cloud,
  passport: Calendar,
  bus: Bus,
  wallet: Wallet,
  calendar: Calendar,
};

/** The full-trip scope is the hero card; the rest are equal-weight presets. */
const HERO_SCOPE = "full_trip";

function durationLabel(seconds: number): string {
  if (seconds < 60) return `~${seconds}s`;
  const minutes = Math.round(seconds / 60);
  return `~${minutes} min`;
}

export function ScopePicker({
  scopes,
  onPick,
}: {
  scopes: Scope[];
  onPick: (scope: Scope) => void;
}) {
  const hero = scopes.find((scope) => scope.slug === HERO_SCOPE);
  const rest = scopes.filter((scope) => scope.slug !== HERO_SCOPE);

  return (
    <div className="mx-auto w-full max-w-5xl">
      <header className="pt-6 pb-8 text-center">
        <h2 className="font-[family-name:var(--font-display)] text-3xl tracking-tight md:text-4xl">
          Where to next?
        </h2>
        <p className="mx-auto mt-2 max-w-xl text-[var(--muted)]">
          Travel, run by agents. Pick what you need — the agents that matter run,
          and the ones that don&rsquo;t stay out of the way.
        </p>
      </header>

      {hero && <HeroCard scope={hero} onPick={onPick} />}

      <h3 className="mt-10 mb-3 text-sm font-semibold text-[var(--muted)]">
        Or ask one thing
      </h3>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {rest.map((scope, index) => (
          <ScopeCard key={scope.slug} scope={scope} index={index} onPick={onPick} />
        ))}
      </div>
    </div>
  );
}

function HeroCard({ scope, onPick }: { scope: Scope; onPick: (s: Scope) => void }) {
  const Icon = ICONS[scope.icon] ?? Sparkles;
  return (
    <motion.button
      type="button"
      onClick={() => onPick(scope)}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}
      className={cn(
        "group w-full overflow-hidden rounded-[var(--r-lg)] p-6 text-left",
        "border border-[var(--brand-400)]/40",
        "bg-gradient-to-br from-[color-mix(in_srgb,var(--brand-500)_12%,transparent)]",
        "to-[color-mix(in_srgb,var(--accent)_10%,transparent)]",
        "shadow-[var(--shadow-1)] transition-all duration-[var(--dur)] ease-[var(--ease)]",
        "hover:border-[var(--brand-400)] hover:shadow-[var(--shadow-2)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
      )}
    >
      <div className="flex items-start gap-4">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-[var(--r-md)] bg-[var(--brand-500)] text-white shadow-[var(--shadow-1)]">
          <Icon className="h-6 w-6" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-[family-name:var(--font-display)] text-xl font-semibold tracking-tight">
              {scope.label}
            </h3>
            <Badge variant="brand">{scope.agent_count} agents</Badge>
            <Badge>{durationLabel(scope.estimate_seconds)}</Badge>
            {scope.auto_itinerary && <Badge variant="info">auto itinerary</Badge>}
          </div>
          <p className="mt-2 text-sm leading-relaxed text-[var(--muted)]">
            {scope.description}
          </p>
          <span className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-[var(--brand-500)]">
            {scope.cta}
            <span className="transition-transform duration-[var(--dur)] group-hover:translate-x-0.5">
              →
            </span>
          </span>
        </div>
      </div>
    </motion.button>
  );
}

function ScopeCard({
  scope,
  index,
  onPick,
}: {
  scope: Scope;
  index: number;
  onPick: (s: Scope) => void;
}) {
  const Icon = ICONS[scope.icon] ?? Compass;
  return (
    <motion.button
      type="button"
      onClick={() => onPick(scope)}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04, duration: 0.24, ease: [0.2, 0.8, 0.2, 1] }}
      className={cn(
        "surface-card group flex h-full flex-col p-4 text-left",
        "transition-all duration-[var(--dur)] ease-[var(--ease)]",
        "hover:border-[var(--brand-400)] hover:shadow-[var(--shadow-2)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
      )}
    >
      <div className="flex items-center gap-2.5">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[var(--r-sm)] bg-[color-mix(in_srgb,var(--brand-400)_14%,transparent)] text-[var(--brand-500)]">
          <Icon className="h-[18px] w-[18px]" />
        </span>
        <h4 className="min-w-0 text-sm font-semibold">{scope.label}</h4>
      </div>

      <p className="mt-2.5 flex-1 text-xs leading-relaxed text-[var(--muted)]">
        {scope.description}
      </p>

      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[0.65rem] text-[var(--muted)]">
          <Badge>{scope.agent_count} agents</Badge>
          {durationLabel(scope.estimate_seconds)}
        </span>
        <span className="text-xs font-medium text-[var(--brand-500)] transition-transform duration-[var(--dur)] group-hover:translate-x-0.5">
          →
        </span>
      </div>
    </motion.button>
  );
}
