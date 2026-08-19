/**
 * OptionCard — renders a single flight/hotel/activity option with reasoning,
 * price, halal badge, and verified indicator (spec §3.2 explainability).
 */

import { CheckCircle, AlertTriangle } from "@/components/ui/icons";
import { cn } from "@/lib/cn";
import { Badge } from "./Badge";
import type { PlanOption } from "@/stores/planStore";

interface OptionCardProps {
  option: PlanOption;
  className?: string;
}

const KIND_LABELS: Record<string, string> = {
  flight: "Flight",
  hotel: "Hotel",
  activity: "Activity",
  restaurant: "Restaurant",
  transport: "Transport",
};

const HALAL_BADGE_VARIANT = {
  certified: "success" as const,
  muslim_friendly: "info" as const,
  unverified: "warning" as const,
};

export function OptionCard({ option, className }: OptionCardProps) {
  return (
    <article
      className={cn(
        "surface-card p-4 flex flex-col gap-3",
        className,
      )}
    >
      {/* Header row: kind badge + title */}
      <div className="flex items-start gap-2">
        <Badge variant="brand">{KIND_LABELS[option.kind] ?? option.kind}</Badge>
        {option.halal_confidence && (
          <Badge variant={HALAL_BADGE_VARIANT[option.halal_confidence]}>
            {option.halal_confidence === "certified" ? "Halal Certified" :
             option.halal_confidence === "muslim_friendly" ? "Muslim Friendly" :
             "Unverified"}
          </Badge>
        )}
        {option.verified && (
          <Badge variant="success">
            <CheckCircle className="h-3 w-3" /> Verified
          </Badge>
        )}
      </div>

      <h3 className="text-sm font-semibold leading-tight">{option.title}</h3>

      {/* Price */}
      {option.price_amount != null && (
        <p className="text-lg font-bold text-[var(--brand-500)]">
          {option.price_currency ?? "MYR"} {Number(option.price_amount).toLocaleString()}
        </p>
      )}

      {/* Reasoning — the "Why did Journava choose this?" */}
      {option.reasoning && (
        <p className="text-xs text-[var(--muted)] leading-relaxed italic">
          &ldquo;{option.reasoning}&rdquo;
        </p>
      )}

      {/* Provider + last checked */}
      <div className="mt-auto flex items-center gap-2 text-[0.65rem] text-[var(--muted)]">
        {option.provider && <span>{option.provider}</span>}
        {option.last_checked && (
          <span className="flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" />
            Checked: {option.last_checked}
          </span>
        )}
      </div>
    </article>
  );
}
