"""Immersive map itinerary (feature) — geocode the day-by-day plan and hand the
frontend everything it needs to draw a real map: a tile style, per-day markers,
route polylines, and walking-time legs.

Keyless-first: if a MapTiler key is in the vault we use MapTiler tiles +
geocoding (nicer, faster, higher limits); otherwise we fall back to OpenStreetMap
raster tiles + Nominatim geocoding so the map works out of the box with no key.
Every geocode is cached (24h), so a second load of the same trip is instant.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from math import asin, cos, radians, sin, sqrt
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agents.goal_parser import CITY_CODES
from app.core import cache, vault
from app.core.settings import settings

logger = logging.getLogger("journava")

# Reverse the city→IATA table into IATA→city, preferring the fullest proper name
# per code ("kuala lumpur" over "kl"/"klia"), so a trip whose destination was
# resolved to an airport code (e.g. "NRT") still geocodes as its city ("Tokyo").
_IATA_TO_CITY: dict[str, str] = {}
for _name, _code in CITY_CODES.items():
    _cur = _IATA_TO_CITY.get(_code)
    if _cur is None or len(_name) > len(_cur):
        _IATA_TO_CITY[_code] = _name


def _resolve_city(destination: str) -> str:
    """A human city name for geocoding — turns a bare IATA code into its city."""
    d = destination.strip()
    if len(d) == 3 and d.isalpha():
        city = _IATA_TO_CITY.get(d.upper())
        if city:
            return city.title()
    return destination


# Itinerary titles carry human decoration a geocoder chokes on — a stop count,
# a sub-attraction, a tagline. Cut at the first such separator to leave the
# core place name ("Narita City Park – Cherry Blossom Walk" → "Narita City Park").
_TITLE_SEPARATORS = (" · ", " – ", " — ", " (", " — ", ": ", " & ")


def _clean_title(title: str) -> str:
    t = (title or "").strip()
    for sep in _TITLE_SEPARATORS:
        idx = t.find(sep)
        if idx > 0:
            t = t[:idx]
    return t.strip(" -·–—")


def _anchor(name: str) -> str | None:
    """A broader query for an over-specific title — its first two words, which
    are usually the real landmark ("Kansai Airport Halal Ramen" → "Kansai
    Airport", "Minoo Park Waterfall Trail" → "Minoo Park")."""
    words = [w for w in name.split() if w]
    return " ".join(words[:2]) if len(words) >= 3 else None


def _near_city(center: list[float], seed: str) -> list[float]:
    """A deterministic point a short hop from the city centre — the last-resort
    location for a stop the geocoder can't find, so it still appears on the map
    (flagged approximate) instead of silently vanishing."""
    h = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16)
    dlng = ((h % 1000) / 1000.0 - 0.5) * 0.04  # ~±2 km E–W
    dlat = (((h // 1000) % 1000) / 1000.0 - 0.5) * 0.04  # ~±2 km N–S
    return [center[0] + dlng, center[1] + dlat]

router = APIRouter(prefix=f"{settings.api_prefix}/trip", tags=["trip"])

_TIMEOUT = httpx.Timeout(12.0)
_UA = "Journava/1.0 (travel planner; contact fitri@craveasia.com)"
_WALK_M_PER_MIN = 80.0  # ~4.8 km/h
_TRANSIT_M_PER_MIN = 500.0  # ~30 km/h — used past the walkable threshold
_WALK_LIMIT_M = 2500.0
#: Kinds that aren't a place to pin on the map.
_SKIP_KINDS = {"flight", "transport"}


class MapItem(BaseModel):
    title: str
    kind: str | None = None
    day_index: int | None = None
    starts_at: str | None = None


class MapRequest(BaseModel):
    destination: str
    items: list[MapItem] = []


def _osm_style() -> dict[str, Any]:
    """A self-contained MapLibre raster style — NO API key, free to use.

    Uses OpenStreetMap's standard raster tiles. This replaces Carto's Voyager
    CDN, which now stamps "API KEY REQUIRED" over keyless tiles. A raster source
    (not a vector style like OpenFreeMap) is deliberate: it renders reliably
    everywhere and keeps the itinerary pin overlay working. A MapTiler key in the
    vault still upgrades to MapTiler's richer vector styles when present.
    """
    return {
        "version": 8,
        "sources": {
            "osm": {
                "type": "raster",
                "tiles": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
                "tileSize": 256,
                "maxzoom": 19,
                "attribution": "© OpenStreetMap contributors",
            }
        },
        "layers": [{"id": "osm", "type": "raster", "source": "osm"}],
    }


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres between (lat, lng) points."""
    lat1, lng1, lat2, lng2 = map(radians, (a[0], a[1], b[0], b[1]))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * 6371000 * asin(sqrt(h))


async def _geocode_maptiler(query: str, key: str, proximity: tuple[float, float] | None) -> list[float] | None:
    params: dict[str, Any] = {"key": key, "limit": 1}
    if proximity:  # (lat, lng) → MapTiler wants lng,lat
        params["proximity"] = f"{proximity[1]},{proximity[0]}"
    url = f"https://api.maptiler.com/geocoding/{quote(query)}.json"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        feats = (r.json() or {}).get("features") or []
    if not feats:
        return None
    center = feats[0].get("center")  # [lng, lat]
    return [float(center[0]), float(center[1])] if center else None


#: Drop a geocode this far from the trip city — a match on the wrong continent
#: (a geocoder's top hit for an ambiguous name) is worse than no pin at all.
_MAX_FROM_CITY_M = 500_000.0


async def _geocode_photon(query: str, proximity: tuple[float, float] | None) -> list[float] | None:
    # Photon (OSM-based, komoot) allows parallel requests — so the whole
    # itinerary geocodes in ~2s instead of ~1/s serially. Its lat/lon bias is
    # soft, so we still pull several candidates and pick the one nearest the trip
    # city, dropping anything implausibly far.
    params: dict[str, Any] = {"q": query, "limit": 8 if proximity else 1}
    if proximity:
        params["lat"], params["lon"] = proximity[0], proximity[1]
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        r = await client.get("https://photon.komoot.io/api/", params=params)
        r.raise_for_status()
        feats = (r.json() or {}).get("features") or []
    if not feats:
        return None
    coords = [f["geometry"]["coordinates"] for f in feats if (f.get("geometry") or {}).get("coordinates")]
    if not coords:
        return None
    if not proximity:
        return [float(coords[0][0]), float(coords[0][1])]  # [lng, lat]
    best, best_d = None, None
    for lng, lat in coords:
        d = _haversine_m((float(lat), float(lng)), proximity)
        if best_d is None or d < best_d:
            best, best_d = [float(lng), float(lat)], d
    if best is None or (best_d is not None and best_d > _MAX_FROM_CITY_M):
        return None  # nearest candidate is implausibly far → drop it
    return best


async def _geocode_city(name: str, key: str | None) -> list[float] | None:
    """Geocode the trip city itself → [lng, lat], cached.

    Uses an importance-ranked source so an ambiguous name resolves to the famous
    city, not a same-named village (Photon's top hit for "Bangkok" is a village
    in Indonesia; Nominatim ranks the Thai capital first). MapTiler when keyed.
    """
    ckey = f"geocity:{'mt' if key else 'osm'}:{name.lower().strip()}"

    async def produce() -> list[float] | None:
        try:
            if key:
                return await _geocode_maptiler(name, key, None)
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
                r = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": name, "format": "jsonv2", "limit": 1},
                )
                r.raise_for_status()
                rows = r.json() or []
            return [float(rows[0]["lon"]), float(rows[0]["lat"])] if rows else None
        except Exception as exc:  # noqa: BLE001
            logger.info("city geocode failed for %r: %s", name, exc)
            return None

    return await cache.cached(ckey, produce, ttl=settings.cache_ttl_long)


async def _geocode(query: str, key: str | None, proximity: tuple[float, float] | None) -> list[float] | None:
    """Cached geocode → [lng, lat]. MapTiler when keyed, else Photon (parallel)."""
    provider = "mt" if key else "photon"
    prox = f"{proximity[0]:.2f},{proximity[1]:.2f}" if proximity else "none"
    ckey = f"geo:{provider}:{prox}:{query.lower().strip()}"

    async def produce() -> list[float] | None:
        try:
            if key:
                return await _geocode_maptiler(query, key, proximity)
            return await _geocode_photon(query, proximity)
        except Exception as exc:  # noqa: BLE001
            logger.info("geocode failed for %r: %s", query, exc)
            return None

    return await cache.cached(ckey, produce, ttl=settings.cache_ttl_long)


def _leg(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    meters = _haversine_m((a["lat"], a["lng"]), (b["lat"], b["lng"]))
    if meters <= _WALK_LIMIT_M:
        return {"meters": round(meters), "minutes": max(1, round(meters / _WALK_M_PER_MIN)), "mode": "walk"}
    return {"meters": round(meters), "minutes": max(1, round(meters / _TRANSIT_M_PER_MIN)), "mode": "transit"}


@router.post("/map")
async def trip_map(body: MapRequest) -> dict[str, Any]:
    """Geocode the itinerary and return a drawable map payload.

    Returns ``configured: false`` only if even the city can't be geocoded (e.g.
    no network) — the frontend then shows the list view unchanged.
    """
    key = await vault.secret_for("maptiler")
    provider = "maptiler" if key else "osm"
    city_name = _resolve_city(body.destination)

    city = await _geocode_city(city_name, key)
    if not city:
        return {"configured": False, "provider": provider, "reason": "could not geocode destination"}
    proximity = (city[1], city[0])  # (lat, lng) for biasing subsequent lookups

    # Geocode each place, biased toward the city. Bound concurrency to 3: the
    # keyless Photon instance rate-limits a big parallel burst, which used to drop
    # the *later* stops (day 2 & 3) and leave those days with no pins or legs. A
    # small semaphore + one retry makes every day resolve as reliably as day 1.
    sem = asyncio.Semaphore(3)

    async def _try(name: str) -> list[float] | None:
        pt = await _geocode(name, key, proximity)
        if not pt:
            pt = await _geocode(f"{name}, {city_name}", key, proximity)
        return pt

    async def locate(item: MapItem) -> dict[str, Any] | None:
        kind = (item.kind or "activity").lower()
        if kind in _SKIP_KINDS:
            return None  # a flight/transfer isn't a place on the map
        name = _clean_title(item.title)
        if not name:
            return None
        async with sem:
            # Many titles already carry the locale ("Naritasan Shinshoji Temple"),
            # so try the bare name first (nearest-to-city wins), then a city-
            # qualified query. One backed-off retry rides out a transient 429.
            pt = await _try(name)
            if not pt:
                await asyncio.sleep(0.4)
                pt = await _try(name)
            # Still nothing? Try the broader landmark anchor ("Kansai Airport
            # Halal Ramen" → "Kansai Airport"), which usually resolves.
            if not pt:
                anchor = _anchor(name)
                if anchor and anchor.lower() != name.lower():
                    pt = await _geocode(f"{anchor}, {city_name}", key, proximity)
        approx = False
        if not pt:
            # Never drop a stop: an AI-suggested venue may not exist in the
            # geocoder, but the map must still show the SAME stops as the
            # itinerary. Pin it near the city centre and flag it approximate.
            logger.info("map: approximating %r near %s (no geocode)", name, city_name)
            pt = _near_city(city, item.title)
            approx = True
        day = item.day_index if isinstance(item.day_index, int) and item.day_index > 0 else 1
        return {
            "title": item.title,
            "kind": item.kind or "activity",
            "day_index": day,
            "starts_at": item.starts_at,
            "lng": pt[0],
            "lat": pt[1],
            "approx": approx,
        }

    located = [p for p in await asyncio.gather(*[locate(it) for it in body.items]) if p]

    # Group by day, order within a day by starts_at, build legs.
    by_day: dict[int, list[dict[str, Any]]] = {}
    for p in located:
        by_day.setdefault(int(p["day_index"]), []).append(p)
    days = []
    for d in sorted(by_day):
        pts = sorted(by_day[d], key=lambda x: x.get("starts_at") or "")
        legs = [_leg(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        days.append({"day": d, "places": pts, "legs": legs})

    style: Any = f"https://api.maptiler.com/maps/streets-v2/style.json?key={key}" if key else _osm_style()
    return {
        "configured": True,
        "provider": provider,
        "style": style,
        "center": city,  # [lng, lat]
        "located": len(located),
        "requested": len(body.items),
        "days": days,
    }


# --------------------------------------------------------------------------- #
# Auto-detect the traveller's location on app open (reverse geocode).
#
# Keyless-first, mirroring the map: browser GPS → Nominatim reverse; if the
# client sends no coordinates (permission denied), fall back to IP geolocation
# off the forwarded client address. Purely a convenience to pre-fill the home
# airport — never clobbers a value the traveller already chose (the frontend
# gates on an empty field).
# --------------------------------------------------------------------------- #

geo_router = APIRouter(prefix=f"{settings.api_prefix}/geo", tags=["geo"])

#: City name → IATA, so a detected city can pre-fill the home field with a real
#: airport code the flight agent already understands ("Kuala Lumpur" → "KUL").
_CITY_TO_IATA: dict[str, str] = {name.lower(): code for name, code in CITY_CODES.items()}

#: Private/loopback ranges — IP geolocation is pointless for these (the demo runs
#: on localhost), so we skip the lookup rather than return a bogus city.
_PRIVATE_IP_PREFIXES = ("127.", "10.", "192.168.", "::1", "fc", "fd", "169.254.")


def _iata_for_city(city: str) -> str | None:
    return _CITY_TO_IATA.get((city or "").strip().lower())


class ReverseGeoRequest(BaseModel):
    lat: float | None = None
    lon: float | None = None


async def _reverse_nominatim(lat: float, lon: float) -> dict[str, Any] | None:
    """(lat, lon) → {city, country, country_code} via keyless Nominatim reverse."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
            r = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "lat": lat,
                    "lon": lon,
                    "format": "jsonv2",
                    "zoom": 10,  # city level
                    "accept-language": "en",
                },
            )
            r.raise_for_status()
            data = r.json() or {}
    except Exception as exc:  # noqa: BLE001
        logger.info("reverse geocode failed for %s,%s: %s", lat, lon, exc)
        return None
    addr = data.get("address") or {}
    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality")
        or addr.get("county")
        or addr.get("state")
    )
    country = addr.get("country")
    if not city and not country:
        return None
    return {"city": city, "country": country, "country_code": (addr.get("country_code") or "").upper()}


def _is_private_ip(ip: str) -> bool:
    if not ip:
        return True
    if ip.startswith(_PRIVATE_IP_PREFIXES):
        return True
    # 172.16.0.0 – 172.31.255.255
    if ip.startswith("172."):
        try:
            return 16 <= int(ip.split(".")[1]) <= 31
        except (IndexError, ValueError):
            return False
    return False


async def _ip_locate(ip: str) -> dict[str, Any] | None:
    """Best-effort IP → city via keyless ip-api. Useless on localhost (skipped)."""
    if _is_private_ip(ip):
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,city,country,countryCode"},
            )
            r.raise_for_status()
            data = r.json() or {}
    except Exception as exc:  # noqa: BLE001
        logger.info("ip geolocation failed for %s: %s", ip, exc)
        return None
    if data.get("status") != "success":
        return None
    return {
        "city": data.get("city"),
        "country": data.get("country"),
        "country_code": (data.get("countryCode") or "").upper(),
    }


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


@geo_router.post("/reverse")
async def geo_reverse(body: ReverseGeoRequest, request: Request) -> dict[str, Any]:
    """Resolve the caller's location to a city (+ airport code when known)."""
    result: dict[str, Any] | None = None
    source: str | None = None

    if body.lat is not None and body.lon is not None:
        lat, lon = body.lat, body.lon

        async def produce() -> dict[str, Any] | None:
            return await _reverse_nominatim(lat, lon)

        result = await cache.cached(
            f"revgeo:{lat:.3f},{lon:.3f}", produce, ttl=settings.cache_ttl_long
        )
        source = "gps" if result else None

    if not result:
        result = await _ip_locate(_client_ip(request))
        source = "ip" if result else source

    if not result or not (result.get("city") or result.get("country")):
        return {"detected": False}

    city = result.get("city") or ""
    country = result.get("country") or ""
    iata = _iata_for_city(city) if city else None
    return {
        "detected": True,
        "source": source,
        "city": city,
        "country": country,
        "country_code": result.get("country_code"),
        "iata": iata,
        "label": ", ".join(p for p in (city, country) if p),
        #: What to pre-fill the home-airport field with: a real IATA when we can
        #: map the city, else the city name (the planner resolves either).
        "home_value": iata or city,
    }
