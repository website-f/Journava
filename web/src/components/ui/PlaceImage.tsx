import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";

/**
 * A lazy, self-resolving photo for a place. Calls the keyless `/places/image`
 * proxy (Openverse → Wikipedia), caches per query for the session, and renders
 * the `fallback` (an icon/placeholder) until an image resolves — or forever if
 * none exists. Used on the public shared-plan + hotel pages and anywhere a stop
 * needs a thumbnail without the caller wiring up its own fetch.
 */
const cache = new Map<string, string | null>();

export function PlaceImage({
  query,
  city = "",
  alt = "",
  className,
  fallback = null,
}: {
  query: string;
  city?: string;
  alt?: string;
  className?: string;
  fallback?: ReactNode;
}) {
  const key = `${query}|${city}`;
  const [src, setSrc] = useState<string | null>(() => cache.get(key) ?? null);

  useEffect(() => {
    if (cache.has(key)) {
      setSrc(cache.get(key) ?? null);
      return;
    }
    let cancelled = false;
    api
      .get<{ image: string | null }>(`/places/image?q=${encodeURIComponent(query)}&city=${encodeURIComponent(city)}`)
      .then((d) => {
        cache.set(key, d.image ?? null);
        if (!cancelled) setSrc(d.image ?? null);
      })
      .catch(() => cache.set(key, null));
    return () => {
      cancelled = true;
    };
  }, [key, query, city]);

  if (src) return <img src={src} alt={alt} loading="lazy" className={className} />;
  return <>{fallback}</>;
}

/** A Google Maps search link for "what/where is this place". */
export function mapsSearchUrl(place: string, city = ""): string {
  const q = [place, city].filter(Boolean).join(", ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`;
}
