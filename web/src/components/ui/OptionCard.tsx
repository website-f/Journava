/**
 * OptionCard — renders a single flight/hotel/activity option with reasoning,
 * price, halal badge, and verified indicator (spec §3.2 explainability).
 */

import { useState } from "react";
import { toast } from "sonner";
import { CheckCircle, AlertTriangle, Building2, ExternalLink } from "@/components/ui/icons";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Badge } from "./Badge";
import { Button } from "./Button";
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
  const listingId =
    option.source === "supplier" ? (option.raw?.listing_id as string | undefined) : undefined;
  const [booking, setBooking] = useState(false);
  const [sent, setSent] = useState(false);

  const bookDirect = async () => {
    if (!listingId || booking || sent) return;
    setBooking(true);
    try {
      await api.post("/supplier/leads", { listing_id: listingId });
      setSent(true);
      toast.success("Request sent — the property will follow up with you directly.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not send your request");
    } finally {
      setBooking(false);
    }
  };

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
        {option.source === "supplier" && (
          <Badge variant="success">
            <Building2 className="h-3 w-3" /> Direct · no OTA fee
          </Badge>
        )}
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

      {/* Provider + last checked + the page a crawled fare was read from */}
      <div className="mt-auto flex items-center gap-2 text-[0.65rem] text-[var(--muted)]">
        {option.provider && <span className="truncate">{option.provider}</span>}
        {option.last_checked && (
          <span className="flex shrink-0 items-center gap-1">
            <AlertTriangle className="h-3 w-3" />
            {option.last_checked}
          </span>
        )}
        {option.source_url && (
          <a
            href={option.source_url}
            target="_blank"
            rel="noreferrer noopener"
            title={option.source_url}
            className="ml-auto inline-flex shrink-0 items-center gap-1 font-medium text-[var(--brand-500)] hover:underline"
          >
            <ExternalLink className="h-3 w-3" /> Source
          </a>
        )}
      </div>

      {option.source === "supplier" && listingId && (
        <Button size="sm" onClick={() => void bookDirect()} loading={booking} disabled={sent}>
          {sent ? (
            <>
              <CheckCircle className="h-4 w-4" /> Request sent
            </>
          ) : (
            "Book direct"
          )}
        </Button>
      )}
    </article>
  );
}
