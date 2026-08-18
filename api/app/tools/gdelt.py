"""GDELT Project API — real-time global events, conflicts, and disasters.

GDELT (Global Database of Events, Location, and Tone) monitors events worldwide
from broadcast, print, and web news. Free, no API key required.

Used by Risk Advisory and Crowd agents to detect active threats and predict
safe travel windows.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger(__name__)

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
TIMEOUT = httpx.Timeout(20.0)


async def events(
    query: str,
    *,
    country: str | None = None,
    days: int = 14,
    max_records: int = 20,
) -> list[dict[str, Any]]:
    """Fetch recent news events for a query/country. Cached for 6h.

    Returns a list of article dicts with keys: title, url, source, seendate, tone.
    """

    params: dict[str, Any] = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": max_records,
        "timespan": f"{days}days",
        "sort": "datedesc",
        "sourceml": "english",
    }
    if country:
        params["sourcecountry"] = country

    async def fetch() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(GDELT_DOC_URL, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("articles", [])

    key = f"gdelt:events:{query}:{country}:{days}"
    try:
        return await cached(key, fetch, ttl=settings.cache_ttl_short)
    except Exception as exc:  # noqa: BLE001
        logger.warning("GDELT events query failed for '%s': %s", query, exc)
        return []


async def tone_analysis(
    country: str,
    *,
    days: int = 14,
) -> dict[str, Any]:
    """Get average media tone for a country (negative = instability). Cached 6h.

    Returns {"avg_tone": float, "num_articles": int, "threat_keywords": list[str]}
    """

    params: dict[str, Any] = {
        "query": country,
        "mode": "tonechart",
        "format": "json",
        "timespan": f"{days}days",
        "sourcecountry": country,
    }

    async def fetch() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(GDELT_DOC_URL, params=params)
            response.raise_for_status()
            data = response.json()
            # Parse tone data — GDELT returns a timeline of tone scores
            tone_data = data.get("timeline", {}).get("data", [])
            if not tone_data:
                return {"avg_tone": 0.0, "num_articles": 0, "threat_keywords": []}

            tones = [float(d.get("tone", 0)) for d in tone_data if "tone" in d]
            avg = sum(tones) / len(tones) if tones else 0.0
            return {
                "avg_tone": round(avg, 2),
                "num_articles": len(tone_data),
                "threat_keywords": [],
            }

    key = f"gdelt:tone:{country}:{days}"
    try:
        return await cached(key, fetch, ttl=settings.cache_ttl_short)
    except Exception as exc:  # noqa: BLE001
        logger.warning("GDELT tone query failed for '%s': %s", country, exc)
        return {"avg_tone": 0.0, "num_articles": 0, "threat_keywords": []}


async def threat_keywords(country: str, *, days: int = 14) -> list[str]:
    """Fetch top threat-related keywords from recent news. Cached 6h."""
    THREAT_TERMS = ["conflict", "war", "attack", "protest", "earthquake",
                    "flood", "hurricane", "terror", "unrest", "epidemic"]
    articles = await events(country, country=country, days=days)
    if not articles:
        return []

    found: list[str] = []
    all_titles = " ".join(a.get("title", "").lower() for a in articles)
    for term in THREAT_TERMS:
        if term in all_titles:
            found.append(term)
    return found
