import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ExternalLink, ShoppingCart, Video, Building2, CheckCircle, Image as ImageIcon, MapPin, Utensils } from "@/components/ui/icons";
import { Button } from "@/components/ui";
import { OtaLinks } from "@/components/ui/OtaLinks";
import { BookingMark } from "@/components/ui/BookingMark";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { useBookings, hotelKey } from "@/stores/bookingsStore";
import { api } from "@/lib/api";
import type { PlanOption } from "@/lib/types";

/**
 * One place / stay / eatery card: name, price (or price range), a source tag
 * (so you can tell a Camofox-read page from a direct-API result), a review
 * snippet, a View/Book button, and — for places & eateries — a "Video" button
 * that opens a real-life YouTube look at the spot.
 */
export function PlaceCard({ option, city }: { option: PlanOption; city?: string }) {
  const raw = (option.raw ?? {}) as {
    price_range?: string | null;
    rating?: number | string | null;
    review?: string | null;
    environment?: string | null;
    image_url?: string | null;
    image?: string | null;
    direct?: boolean;
    listing_id?: string;
    original_price?: number | null;
    discount_pct?: number | null;
    ota_links?: { name: string; url: string }[] | null;
  };
  const link = option.booking_url || option.source_url || null;
  const isStay = option.kind === "hotel";
  const isDirect = option.source === "supplier";
  const canVideo = option.kind === "activity" || option.kind === "restaurant";
  const bkey = isStay ? hotelKey(option.title) : "";
  const booked = useBookings((s) => Boolean(bkey) && s.marks.some((m) => m.item_key === bkey));
  const [videoLoading, setVideoLoading] = useState(false);

  // Book-direct (supplier listing → a lead the property follows up on).
  const [booking, setBooking] = useState(false);
  const [sent, setSent] = useState(false);
  const bookDirect = async () => {
    if (!raw.listing_id || booking || sent) return;
    setBooking(true);
    try {
      await api.post("/supplier/leads", { listing_id: raw.listing_id });
      setSent(true);
      toast.success("Request sent — the property will follow up with you directly.");
    } catch {
      toast.error("Could not send your request.");
    } finally {
      setBooking(false);
    }
  };

  // A real photo — the supplier's own listing image first, else lazy Openverse/Wikipedia.
  const [image, setImage] = useState<string | null>(raw.image_url ?? raw.image ?? null);
  useEffect(() => {
    if (image) return;
    let cancelled = false;
    api
      .get<{ image: string | null }>(
        `/places/image?q=${encodeURIComponent(option.title)}&city=${encodeURIComponent(city ?? "")}`,
      )
      .then((r) => !cancelled && r.image && setImage(r.image))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [option.title, city]); // eslint-disable-line react-hooks/exhaustive-deps

  const seeVideo = async () => {
    setVideoLoading(true);
    const fallback = `https://www.youtube.com/results?search_query=${encodeURIComponent(`${option.title} ${city ?? ""} travel`)}`;
    // Open the tab synchronously so the click gesture beats popup-blockers, then
    // redirect it once resolved. IMPORTANT: do NOT pass "noopener" here — with it
    // window.open returns null, leaving an un-redirectable blank tab (the bug).
    // We sever the opener manually instead.
    const tab = window.open("", "_blank");
    if (tab) {
      try {
        tab.opener = null;
      } catch {
        /* cross-origin guard — safe to ignore */
      }
    }
    const go = (url: string) => {
      if (tab) tab.location.href = url;
      else window.open(url, "_blank"); // popup was blocked — try a fresh open
    };
    try {
      const res = await api.get<{ url: string }>(
        `/places/video?q=${encodeURIComponent(option.title)}&city=${encodeURIComponent(city ?? "")}`,
      );
      go(res.url || fallback);
    } catch {
      go(fallback);
    } finally {
      setVideoLoading(false);
    }
  };
  const price =
    option.price_amount != null
      ? `${option.price_currency ?? ""} ${Number(option.price_amount).toLocaleString()}`.trim()
      : raw.price_range || null;

  return (
    <div className="surface-card flex h-full flex-col overflow-hidden p-4 transition-colors hover:border-[var(--brand-400)]">
      {/* Fixed-height thumbnail area (placeholder when the source has no image)
          so every card — stays, places, eats — is the same height in the grid. */}
      <div className="-mx-4 -mt-4 mb-3 h-28 w-[calc(100%+2rem)] overflow-hidden bg-[color-mix(in_srgb,var(--brand-400)_12%,transparent)]">
        {image ? (
          <img
            src={image}
            alt={option.title}
            loading="lazy"
            onError={() => setImage(null)}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="grid h-full w-full place-items-center text-[var(--brand-500)] opacity-35">
            {isStay ? <Building2 className="h-8 w-8" weight="duotone" /> : option.kind === "restaurant" ? <Utensils className="h-8 w-8" weight="duotone" /> : option.kind === "activity" ? <MapPin className="h-8 w-8" weight="duotone" /> : <ImageIcon className="h-8 w-8" weight="duotone" />}
          </div>
        )}
      </div>
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 text-sm font-semibold">{option.title}</p>
        {price && (
          <span className="shrink-0 text-right text-sm font-semibold text-[var(--brand-500)]">
            {raw.original_price && option.price_amount != null && raw.original_price > option.price_amount ? (
              <span className="mr-1 text-xs font-normal text-[var(--muted)] line-through">
                {option.price_currency} {raw.original_price.toLocaleString()}
              </span>
            ) : null}
            {price}
          </span>
        )}
      </div>
      {isDirect && (
        <span className="mt-1 inline-flex w-fit items-center gap-1 rounded-[var(--r-pill)] bg-[color-mix(in_srgb,var(--success)_14%,transparent)] px-2 py-0.5 text-[0.6rem] font-semibold text-[var(--success)]">
          <Building2 className="h-3 w-3" /> Direct · no OTA fee
          {raw.discount_pct ? <span className="ml-1">· -{raw.discount_pct}%</span> : null}
        </span>
      )}
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

      {!(isStay && booked) && (link || canVideo || (isDirect && raw.listing_id)) && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {isDirect && raw.listing_id && (
            <Button size="sm" onClick={() => void bookDirect()} loading={booking} disabled={sent}>
              {sent ? <><CheckCircle className="h-4 w-4" /> Request sent</> : <><ShoppingCart className="h-4 w-4" /> Book direct</>}
            </Button>
          )}
          {link && (
            <Button asChild size="sm" variant={isStay ? undefined : "secondary"}>
              <a href={link} target="_blank" rel="noreferrer noopener">
                {isStay ? <ShoppingCart className="h-4 w-4" /> : <ExternalLink className="h-4 w-4" />}
                {isStay ? "View & book" : "View"}
              </a>
            </Button>
          )}
          {canVideo && (
            <Button size="sm" variant="ghost" loading={videoLoading} onClick={() => void seeVideo()}>
              <Video className="h-4 w-4" />
              Video
            </Button>
          )}
        </div>
      )}

      {isStay && !isDirect && !booked && <OtaLinks links={raw.ota_links} label="Compare & book" />}

      {isStay && (
        <BookingMark
          kind="hotel"
          itemKey={bkey}
          title={option.title}
          provider={option.provider}
          priceAmount={option.price_amount}
          priceCurrency={option.price_currency}
          snapshot={{ title: option.title, provider: option.provider, price_amount: option.price_amount, price_currency: option.price_currency, raw: option.raw }}
        />
      )}
    </div>
  );
}
