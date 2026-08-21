"""Destination imagery — a representative photo URL for a place.

Camofox produces accessibility snapshots, not screenshots, so a page capture
would be a poor thumbnail anyway. Wikipedia's REST summary gives a keyless,
high-quality lead image for most places (city or country), which makes a far
better trip thumbnail — a real photo of the destination.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)
_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"


async def destination_image(place: str | None) -> str | None:
    """Return a representative photo URL for `place`, or None.

    Uses Wikipedia's lead image for the place's page. Cached (never caches a
    miss, so a transient failure is retried next time).
    """
    if not place:
        return None
    title = place.strip()
    if not title:
        return None

    async def fetch() -> str | None:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": "Journava/1.0 (travel planner)"},
        ) as client:
            resp = await client.get(
                _SUMMARY_URL.format(title=quote(title)), follow_redirects=True
            )
            if resp.status_code != 200:
                return None
            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                return None
            return (data.get("originalimage") or {}).get("source") or (
                data.get("thumbnail") or {}
            ).get("source")

    key = f"img:wiki:{title.lower()}"
    try:
        return await cached(key, fetch, ttl=settings.cache_ttl_long)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Destination image lookup failed for '%s': %s", place, exc)
        return None
