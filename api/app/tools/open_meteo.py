"""Open-Meteo forecast tool — no API key, generous limits (spec §9).

The reference implementation for every tool in this package: async httpx, hard
caching through Redis, graceful failure. Copy this shape for the remaining tools.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT = httpx.Timeout(15.0)


async def geocode(place: str) -> dict[str, Any] | None:
    """Resolve a place name to coordinates. Cached for 24h (places don't move)."""

    async def fetch() -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                GEOCODE_URL, params={"name": place, "count": 1, "language": "en"}
            )
            response.raise_for_status()
            results = response.json().get("results") or []
            return results[0] if results else None

    try:
        return await cached(f"open_meteo:geocode:{place.lower()}", fetch, ttl=settings.cache_ttl_long)
    except Exception as exc:  # noqa: BLE001 - a missing forecast never breaks a plan
        logger.warning("Geocode failed for %s: %s", place, exc)
        return None


async def forecast(
    latitude: float,
    longitude: float,
    *,
    days: int = 7,
) -> dict[str, Any] | None:
    """Daily forecast used by the Weather/Risk agent. Cached for 6h."""

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "forecast_days": days,
        "timezone": "auto",
    }

    async def fetch() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(FORECAST_URL, params=params)
            response.raise_for_status()
            return response.json()

    key = f"open_meteo:forecast:{latitude:.2f},{longitude:.2f}:{days}"
    try:
        return await cached(key, fetch, ttl=settings.cache_ttl_short)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Forecast failed for %s,%s: %s", latitude, longitude, exc)
        return None
