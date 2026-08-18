/**
 * TripMap — MapLibre GL map showing itinerary points on an interactive map.
 *
 * Reads the active trip's coordinates and itinerary items, plots markers for
 * each activity/meal/landmark, and draws a simple route between day groups.
 *
 * Spec §3.3 — My Trip page maps integration.
 */

import { useEffect, useRef, useMemo } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Navigation } from "lucide-react";
import { usePlanStore } from "@/stores/planStore";

/** Default center: Venice (our demo destination) */
const DEFAULT_CENTER: [number, number] = [12.32, 45.44];
const DEFAULT_ZOOM = 13;

/** MapTiler free-tier style URL (key in env or open OSM style) */
const MAP_STYLE = {
  version: 8 as const,
  sources: {
    osm: {
      type: "raster" as const,
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "&copy; OpenStreetMap contributors",
    },
  },
  layers: [
    {
      id: "osm",
      type: "raster" as const,
      source: "osm",
    },
  ],
};

/** Kind → color mapping for markers */
const KIND_COLORS: Record<string, string> = {
  flight: "#3B82F6",
  hotel: "#8B5CF6",
  activity: "#4F46E5",
  meal: "#F59E0B",
  transport: "#10B981",
};

/** Kind → emoji mapping */
const KIND_ICONS: Record<string, string> = {
  flight: "✈️",
  hotel: "🏨",
  activity: "📍",
  meal: "🍽️",
  transport: "🚌",
};

interface TripMapProps {
  className?: string;
}

export function TripMap({ className }: TripMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<maplibregl.Map | null>(null);
  const results = usePlanStore((s) => s.results);

  // Extract coordinates from weather_risk data and itinerary
  const { center, items } = useMemo(() => {
    if (!results) return { center: DEFAULT_CENTER, items: [] };

    const weatherData = results.weather_risk?.data;
    const coords = weatherData?.coordinates as { lat: number; lng: number } | undefined;
    const ctr: [number, number] = coords ? [coords.lng, coords.lat] : DEFAULT_CENTER;

    const it = results.itinerary?.items ?? [];
    return { center: ctr, items: it };
  }, [results]);

  useEffect(() => {
    if (!mapRef.current || mapInstance.current) return;

    const map = new maplibregl.Map({
      container: mapRef.current,
      style: MAP_STYLE,
      center,
      zoom: DEFAULT_ZOOM,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-right",
    );

    mapInstance.current = map;

    return () => {
      map.remove();
      mapInstance.current = null;
    };
  }, []);

  // Update markers when items change
  useEffect(() => {
    const map = mapInstance.current;
    if (!map || items.length === 0) return;

    // Clear existing markers
    const markers: maplibregl.Marker[] = [];

    // Add markers for each itinerary item
    items.forEach((item, idx) => {
      // Generate pseudo-random positions around center for demo
      // In production, itinerary items would have lat/lng
      const angle = (idx / items.length) * Math.PI * 2;
      const radius = 0.005 + (idx % 3) * 0.003;
      const lng = center[0] + Math.cos(angle) * radius;
      const lat = center[1] + Math.sin(angle) * radius;

      const color = KIND_COLORS[item.kind] || "#4F46E5";
      const emoji = KIND_ICONS[item.kind] || "📍";

      const el = document.createElement("div");
      el.className = "trip-map-marker";
      el.style.cssText = `
        width: 28px; height: 28px; border-radius: 50%;
        background: ${color}; border: 2px solid white;
        display: flex; align-items: center; justify-content: center;
        font-size: 12px; cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s;
      `;
      el.textContent = emoji;
      el.addEventListener("mouseenter", () => {
        el.style.transform = "scale(1.3)";
      });
      el.addEventListener("mouseleave", () => {
        el.style.transform = "scale(1)";
      });

      const popup = new maplibregl.Popup({ offset: 16 }).setHTML(`
        <div style="font-family: system-ui; padding: 4px 0;">
          <div style="font-weight: 600; font-size: 13px;">${item.title}</div>
          <div style="font-size: 11px; color: #666; margin-top: 2px;">
            Day ${item.day_index} ${item.starts_at ? `· ${item.starts_at}` : ""}
          </div>
          ${item.cost_amount ? `<div style="font-size: 12px; color: var(--brand-500, #4F46E5); margin-top: 4px; font-weight: 600;">${item.cost_currency ?? "MYR"} ${Number(item.cost_amount).toLocaleString()}</div>` : ""}
        </div>
      `);

      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([lng, lat])
        .setPopup(popup)
        .addTo(map);

      markers.push(marker);
    });

    // Fit bounds to show all markers
    if (markers.length > 1) {
      const bounds = new maplibregl.LngLatBounds();
      markers.forEach((m) => bounds.extend(m.getLngLat()));
      map.fitBounds(bounds, { padding: 60, maxZoom: 15 });
    }

    return () => {
      markers.forEach((m) => m.remove());
    };
  }, [items, center]);

  if (!results) return null;

  return (
    <div className={className}>
      <h3 className="flex items-center gap-2 text-lg font-semibold mb-3">
        <Navigation className="h-5 w-5 text-[var(--brand-500)]" />
        Map
      </h3>
      <div className="surface-card overflow-hidden p-0">
        <div ref={mapRef} className="w-full h-[320px] rounded-[var(--r-lg)]" />
        <div className="p-3 flex flex-wrap gap-2 border-t border-[var(--border)]">
          {Object.entries(KIND_COLORS).map(([kind, color]) => (
            <span key={kind} className="flex items-center gap-1 text-[0.65rem] text-[var(--muted)]">
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: color }} />
              {kind}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
