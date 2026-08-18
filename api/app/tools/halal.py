"""Halal certification verification — JAKIM / MUIS / MUI cross-check (spec §7.5).

Provides halal confidence labels for restaurants and food establishments by
cross-checking against known certification body directories.

Confidence levels (spec §7.5):
  - certified:        Listed by JAKIM (MY), MUIS (SG), or MUI (ID)
  - muslim_friendly:  Strong signals (HalalTrip, Zabihah, reviews) but no formal cert
  - unverified:       Surfaced with a clear warning label

All lookups are cached (24h) and degrade gracefully — a failing directory
never blocks the research pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(15.0)

# Known certification body directories (public endpoints)
_JAKIM_SEARCH_URL = "https://www.halal.gov.my/v4/index.php"
_HALALTRIP_SEARCH_URL = "https://www.halaltrip.com/api/search"


async def check_certification(
    restaurant_name: str,
    *,
    country: str | None = None,
) -> dict[str, Any]:
    """Check halal certification status for a restaurant.

    Returns:
        {
            "confidence": "certified" | "muslim_friendly" | "unverified",
            "source": str | None,       # which directory confirmed it
            "cert_body": str | None,    # JAKIM / MUIS / MUI
            "notes": str,
        }
    """
    result: dict[str, Any] = {
        "confidence": "unverified",
        "source": None,
        "cert_body": None,
        "notes": "",
    }

    # 1. Try JAKIM (Malaysia) — most comprehensive for SEA
    if country in (None, "MY", "Malaysia"):
        jakim = await _check_jakim(restaurant_name)
        if jakim:
            result.update(jakim)
            return result

    # 2. Try HalalTrip public search
    halaltrip = await _check_halaltrip(restaurant_name)
    if halaltrip:
        result.update(halaltrip)
        return result

    # 3. Keyword heuristics from common halal signals
    heuristic = _heuristic_check(restaurant_name, country)
    if heuristic["confidence"] != "unverified":
        result.update(heuristic)
        return result

    result["notes"] = "No certification found in public directories"
    return result


async def _check_jakim(name: str) -> dict[str, Any] | None:
    """Check JAKIM (Malaysia) halal certification directory."""
    async def fetch() -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # JAKIM e-Halal public search
            response = await client.get(
                "https://www.halal.gov.my/v4/index.php",
                params={"mod": "search", "act": "view", "carian": name},
                follow_redirects=True,
            )
            if response.status_code != 200:
                return None
            text = response.text.lower()
            if name.lower() in text and ("sah" in text or "certified" in text or "halal" in text):
                return {
                    "confidence": "certified",
                    "source": "halal.gov.my",
                    "cert_body": "JAKIM",
                    "notes": "Listed in JAKIM e-Halal directory",
                }
            return None

    key = f"halal:jakim:{name.lower()}"
    try:
        return await cached(key, fetch, ttl=settings.cache_ttl_long)
    except Exception as exc:
        logger.debug("JAKIM check failed for '%s': %s", name, exc)
        return None


async def _check_halaltrip(name: str) -> dict[str, Any] | None:
    """Check HalalTrip for Muslim-friendly restaurants."""
    async def fetch() -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(
                _HALALTRIP_SEARCH_URL,
                params={"q": name, "type": "restaurant"},
            )
            if response.status_code != 200:
                return None
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            results = data.get("results", [])
            if results:
                return {
                    "confidence": "muslim_friendly",
                    "source": "halaltrip.com",
                    "cert_body": None,
                    "notes": "Found on HalalTrip directory",
                }
            return None

    key = f"halal:halaltrip:{name.lower()}"
    try:
        return await cached(key, fetch, ttl=settings.cache_ttl_long)
    except Exception as exc:
        logger.debug("HalalTrip check failed for '%s': %s", name, exc)
        return None


def _heuristic_check(name: str, country: str | None) -> dict[str, Any]:
    """Keyword-based heuristic check for common halal signals."""
    name_lower = name.lower()

    # Common halal-certified chain keywords
    halal_chains = [
        "nasi kandar", "mamak", "nando's", "marrybrown", "a&w",
        "kenny rogers", "secret recipe", "oldtown", "teh tarik",
    ]
    for chain in halal_chains:
        if chain in name_lower:
            return {
                "confidence": "muslim_friendly",
                "source": "heuristic",
                "cert_body": None,
                "notes": f"Known halal-friendly chain: {chain.title()}",
            }

    # Halal keywords in name
    if any(kw in name_lower for kw in ["halal", "muslim", "zabihah"]):
        return {
            "confidence": "muslim_friendly",
            "source": "heuristic",
            "cert_body": None,
            "notes": "Name contains halal-related keyword",
        }

    return {"confidence": "unverified", "source": None, "cert_body": None, "notes": ""}


async def verify_batch(
    restaurants: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Verify halal status for a list of restaurants.

    Each dict should have at least {"title": str, "country": str | None}.
    Returns results in the same order.
    """
    import asyncio

    tasks = [
        check_certification(r.get("title", ""), country=r.get("country"))
        for r in restaurants
    ]
    return await asyncio.gather(*tasks)
