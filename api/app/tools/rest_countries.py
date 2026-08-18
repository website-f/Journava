"""REST Countries API — country information, no API key required.

Provides visa info, currencies, languages, capital, region, and more.
Used by Visa, Language, Emergency, and Payment agents.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://restcountries.com/v3.1"
TIMEOUT = httpx.Timeout(15.0)


async def country_info(name: str) -> dict[str, Any] | None:
    """Fetch comprehensive country info. Cached for 24h.

    Returns a dict with: name, capital, region, currencies, languages,
    timezones, population, area, borders, flag.
    """

    async def fetch() -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{BASE_URL}/name/{name}",
                params={"fields": "name,capital,region,subregion,currencies,languages,"
                        "timezones,population,area,borders,flag,cca2,cca3"},
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            if not data:
                return None
            country = data[0]
            return {
                "name": country.get("name", {}).get("common", name),
                "official_name": country.get("name", {}).get("official", name),
                "capital": (country.get("capital") or [None])[0],
                "region": country.get("region", ""),
                "subregion": country.get("subregion", ""),
                "currencies": list(country.get("currencies", {}).keys()),
                "currency_details": country.get("currencies", {}),
                "languages": list(country.get("languages", {}).values()),
                "timezones": country.get("timezones", []),
                "population": country.get("population", 0),
                "area_km2": country.get("area", 0),
                "borders": country.get("borders", []),
                "flag": country.get("flag", ""),
                "cca2": country.get("cca2", ""),
                "cca3": country.get("cca3", ""),
            }

    key = f"restcountries:{name.lower()}"
    try:
        return await cached(key, fetch, ttl=settings.cache_ttl_long)
    except Exception as exc:  # noqa: BLE001
        logger.warning("REST Countries query failed for '%s': %s", name, exc)
        return None


async def regional_info(region: str) -> list[dict[str, Any]]:
    """Fetch all countries in a region. Cached for 24h."""

    async def fetch() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                f"{BASE_URL}/region/{region}",
                params={"fields": "name,capital,currencies,languages"},
            )
            response.raise_for_status()
            return [
                {
                    "name": c.get("name", {}).get("common"),
                    "capital": (c.get("capital") or [None])[0],
                    "currencies": list(c.get("currencies", {}).keys()),
                }
                for c in response.json()
            ]

    key = f"restcountries:region:{region.lower()}"
    try:
        return await cached(key, fetch, ttl=settings.cache_ttl_long)
    except Exception as exc:  # noqa: BLE001
        logger.warning("REST Countries region query failed for '%s': %s", region, exc)
        return []
