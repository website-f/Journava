import { ExternalLink, ShoppingCart } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { cn } from "@/lib/cn";
import type { PlanOption } from "@/lib/types";

/**
 * One place / stay / eatery card: name, price (or price range), a source tag
 * (so you can tell a Camofox-read page from a direct-API result), a review
 * snippet, and always a View/Book button that opens the source or a maps link.
 */
export function PlaceCard({ option }: { option: PlanOption }) {
  const raw = (option.raw ?? {}) as {
    price_range?: string | null;
    rating?: number | string | null;
    review?: string | null;
    environment?: string | null;
  };
  const link = option.booking_url || option.source_url || null;
  const isStay = option.kind === "hotel";
  const price =
    option.price_amount != null
      ? `${option.price_currency ?? ""} ${Number(option.price_amount).toLocaleString()}`.trim()
      : raw.price_range || null;

  return (
    <div className="surface-card flex flex-col p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 text-sm font-semibold">{option.title}</p>
        {price && (
          <span className="shrink-0 text-sm font-semibold text-[var(--brand-500)]">{price}</span>
        )}
      </div>
      {option.provider && (
        <p className="mt-0.5 text-[0.65rem] text-[var(--muted)]">{option.provider}</p>
      )}

      {(option.reasoning || raw.review) && (
        <p className="mt-1.5 flex-1 text-xs italic text-[var(--muted)]">
          {raw.review || option.reasoning}
        </p>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-[var(--border)] pt-2">
        <SourceBadge source={option.source} environment={raw.environment} />
        {option.verified ? (
          <span className="rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--success)_14%,transparent)] px-2 py-0.5 text-[0.6rem] font-semibold uppercase tracking-wide text-[var(--success)]">
            Verified
          </span>
        ) : (
          <span className="rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--muted)_12%,transparent)] px-2 py-0.5 text-[0.6rem] font-medium uppercase tracking-wide text-[var(--muted)]">
            Indicative
          </span>
        )}
        {raw.rating != null && raw.rating !== "" && (
          <span className="text-[0.65rem] font-medium text-[var(--accent)]">★ {raw.rating}</span>
        )}
      </div>

      {link && (
        <div className="mt-3">
          <Button asChild size="sm" variant={isStay ? undefined : "secondary"} className={cn("w-full sm:w-auto")}>
            <a href={link} target="_blank" rel="noreferrer noopener">
              {isStay ? <ShoppingCart className="h-4 w-4" /> : <ExternalLink className="h-4 w-4" />}
              {isStay ? "View & book" : "View"}
            </a>
          </Button>
        </div>
      )}
    </div>
  );
}
