"""Keyless place photos — a real thumbnail for any named place or destination.

Openverse (CC-licensed image search) first because it returns a scenic photo for
almost any query (a Bali beach, a Doha skyline), then the Wikipedia lead image as
a fallback. Cached, so a card/suggestion resolves its image only once.
"""

from __future__ import annotations

import logging

import httpx

from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger("journava")

_TIMEOUT = httpx.Timeout(8.0)


async def place_photo(query: str) -> str | None:
    """Return a photo thumbnail URL for `query`, or None. Cached 24h."""
    query = (query or "").strip()
    if not query:
        return None
    ckey = f"photo:{query.lower()}"

    async def produce() -> str | None:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": "Journava/1.0"}) as client:
                r = await client.get(
                    "https://api.openverse.org/v1/images/",
                    params={"q": query, "page_size": 1, "mature": "false"},
                )
                if r.status_code == 200:
                    results = (r.json() or {}).get("results") or []
                    if results:
                        return results[0].get("thumbnail") or results[0].get("url")
        except Exception as exc:  # noqa: BLE001
            logger.debug("openverse miss for %r: %s", query, exc)
        try:
            from app.tools import imagery

            img = await imagery.destination_image(query)
            if img:
                return img
        except Exception as exc:  # noqa: BLE001
            logger.debug("wikipedia image miss for %r: %s", query, exc)
        return None

    return await cached(ckey, produce, ttl=settings.cache_ttl_long)
