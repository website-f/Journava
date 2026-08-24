/**
 * TripMap — MapLibre GL map of the itinerary on REAL geocoded coordinates.
 *
 * The plan's places have no lat/lng, so the backend (`POST /trip/map`) geocodes
 * each stop (keyless OSM + Nominatim, upgrading to MapTiler when a key is in the
 * vault), returns a tile style + per-day markers + walking/transit legs, and
 * this component draws them: day tabs, numbered markers, a dashed route line,
 * and a leg strip ("Senso-ji → Skytree · ~18 min walk").
 *
 * Spec §3.3 — My Trip page maps integration.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

/** The GeoJSON shape MapLibre's GeoJSONSource.setData accepts — derived from its
 *  own signature so we don't need the @types/geojson global namespace. */
type RouteData = Parameters<maplibregl.GeoJSONSource["setData"]>[0];
import { Navigation, Footprints, Bus } from "@/components/ui/icons";
import { usePlanStore } from "@/stores/planStore";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

type MapPlace = { title: string; kind: string; day_index: number; starts_at: string | null; lng: number; lat: number };
type MapLeg = { meters: number; minutes: number; mode: "walk" | "transit" };
type MapDay = { day: number; places: MapPlace[]; legs: MapLeg[] };
type MapPayload = {
  configured: boolean;
  provider: string;
  style: string | maplibregl.StyleSpecification;
  center: [number, number];
  located: number;
  requested: number;
  days: MapDay[];
};

const KIND_COLORS: Record<string, string> = {
  flight: "#7C3AED",
  hotel: "#16A34A",
  activity: "#2563EB",
  meal: "#E0973B",
  restaurant: "#E0973B",
  transport: "#0891B2",
};

function markerEl(index: number, color: string): HTMLElement {
  const el = document.createElement("div");
  el.style.cssText = "width:28px;height:28px;cursor:pointer;";
  const bubble = document.createElement("div");
  bubble.style.cssText =
    `width:28px;height:28px;border-radius:50%;background:${color};border:2px solid #fff;` +
    "display:grid;place-items:center;font:600 13px/1 system-ui;color:#fff;" +
    "box-shadow:0 2px 6px rgba(0,0,0,.3);transition:transform .15s ease;";
  bubble.textContent = String(index + 1);
  el.appendChild(bubble);
  el.addEventListener("mouseenter", () => (bubble.style.transform = "scale(1.25)"));
  el.addEventListener("mouseleave", () => (bubble.style.transform = "scale(1)"));
  return el;
}

const short = (t: string) => t.split(" ").slice(0, 2).join(" ");

interface TripMapProps {
  className?: string;
}

export function TripMap({ className }: TripMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const results = usePlanStore((s) => s.results);

  const [payload, setPayload] = useState<MapPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [activeDay, setActiveDay] = useState<number | null>(null);

  const { destination, items } = useMemo(() => {
    const dest = (results?.chief?.data as { destination?: string } | undefined)?.destination ?? "";
    const it = (results?.itinerary?.items ?? []).map((i) => ({
      title: i.title,
      kind: i.kind,
      day_index: i.day_index,
      starts_at: i.starts_at,
    }));
    return { destination: dest, items: it };
  }, [results]);

  // 1) Fetch geocoded coordinates once per (destination, items) signature.
  const sig = useMemo(
    () => `${destination}|${items.map((i) => `${i.day_index}:${i.title}`).join(",")}`,
    [destination, items],
  );
  useEffect(() => {
    let cancelled = false;
    if (!destination || items.length === 0) {
      setPayload(null);
      return;
    }
    setFailed(false);
    api
      .post<MapPayload>("/trip/map", { destination, items })
      .then((res) => {
        if (cancelled) return;
        if (!res.configured || !res.days?.length) {
          setFailed(true);
          return;
        }
        setPayload(res);
        setActiveDay((d) => d ?? res.days[0]?.day ?? 1);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [sig]); // eslint-disable-line react-hooks/exhaustive-deps

  // 2) Create the map once we have a style.
  useEffect(() => {
    if (!payload || !mapRef.current || mapInstance.current) return;
    const map = new maplibregl.Map({
      container: mapRef.current,
      style: payload.style,
      center: payload.center,
      zoom: 12,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    mapInstance.current = map;

    // Keep the canvas sized to its container (tab switches / resizes).
    let raf = 0;
    const scheduleResize = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        map.resize();
      });
    };
    const ro = new ResizeObserver(scheduleResize);
    ro.observe(mapRef.current);
    window.addEventListener("resize", scheduleResize);
    const settle = setTimeout(() => map.resize(), 60);

    return () => {
      clearTimeout(settle);
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener("resize", scheduleResize);
      ro.disconnect();
      map.remove();
      mapInstance.current = null;
    };
  }, [payload]);

  // 3) Redraw markers + route line whenever the active day changes.
  useEffect(() => {
    const map = mapInstance.current;
    if (!map || !payload || activeDay == null) return;
    const day = payload.days.find((d) => d.day === activeDay);
    if (!day) return;

    const draw = () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      const bounds = new maplibregl.LngLatBounds();
      day.places.forEach((p, i) => {
        const color = KIND_COLORS[p.kind] ?? KIND_COLORS.activity;
        const popup = new maplibregl.Popup({ offset: 18, closeButton: false }).setHTML(
          `<div style="font:600 13px system-ui">${i + 1}. ${p.title}</div>` +
            `<div style="font:11px system-ui;color:#667;margin-top:2px">${p.starts_at ? p.starts_at + " · " : ""}${p.kind}</div>`,
        );
        const marker = new maplibregl.Marker({ element: markerEl(i, color) })
          .setLngLat([p.lng, p.lat])
          .setPopup(popup)
          .addTo(map);
        markersRef.current.push(marker);
        bounds.extend([p.lng, p.lat]);
      });

      const line = {
        type: "Feature",
        geometry: { type: "LineString", coordinates: day.places.map((p) => [p.lng, p.lat]) },
        properties: {},
      } as RouteData;
      const src = map.getSource("route") as maplibregl.GeoJSONSource | undefined;
      if (src) {
        src.setData(line);
      } else {
        map.addSource("route", { type: "geojson", data: line });
        map.addLayer({
          id: "route",
          type: "line",
          source: "route",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": "#0F766E", "line-width": 3, "line-dasharray": [1, 1.6] },
        });
      }
      if (day.places.length) map.fitBounds(bounds, { padding: 56, maxZoom: 15, duration: 600 });
    };

    if (map.isStyleLoaded()) draw();
    else map.once("load", draw);
  }, [activeDay, payload]);

  if (!results || failed || (!payload && items.length === 0)) return null;

  const day = payload?.days.find((d) => d.day === activeDay);
  return (
    <div className={className}>
      <h3 className="mb-3 flex items-center gap-2 text-lg font-semibold">
        <Navigation className="h-5 w-5 text-[var(--brand-500)]" />
        Map
      </h3>
      <div className="surface-card overflow-hidden p-0">
        {payload && (
          <div className="flex flex-wrap gap-1 border-b border-[var(--border)] px-3 py-2">
            {payload.days.map((d) => (
              <button
                key={d.day}
                type="button"
                onClick={() => setActiveDay(d.day)}
                className={cn(
                  "rounded-[var(--r-pill)] px-2.5 py-1 text-xs font-medium transition-colors",
                  d.day === activeDay
                    ? "bg-[var(--brand-500)] text-white"
                    : "bg-[var(--bg)] text-[var(--muted)] hover:text-[var(--text)]",
                )}
              >
                Day {d.day}
              </button>
            ))}
          </div>
        )}
        <div ref={mapRef} className="h-[300px] w-full sm:h-[380px] lg:h-[440px]" />
        {day && day.legs.length > 0 && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 border-t border-[var(--border)] px-3 py-2 text-[0.7rem] text-[var(--muted)]">
            {day.legs.map((lg, i) => (
              <span key={i} className="inline-flex items-center gap-1">
                {lg.mode === "walk" ? <Footprints className="h-3 w-3" /> : <Bus className="h-3 w-3" />}
                {short(day.places[i]?.title ?? "")} → {short(day.places[i + 1]?.title ?? "")}
                <span className="font-medium text-[var(--text)]">~{lg.minutes} min {lg.mode}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
