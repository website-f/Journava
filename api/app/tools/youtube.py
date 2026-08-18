"""YouTube Data API tool — video search + view stats (spec §9).

Used by the Research Agent for destination video intelligence (travel vlogs,
halal food guides, walking tours). Falls back gracefully when the API key is
absent or the quota is exhausted.

Free tier: 10,000 units/day.  A search costs 100 units → ~100 searches/day.
Cache aggressively (12h) to stay within quota.

Endpoint: https://www.googleapis.com/youtube/v3/search
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core import vault
from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
TIMEOUT = httpx.Timeout(15.0)


async def search_videos(
    query: str,
    *,
    max_results: int = 5,
    order: str = "relevance",
) -> list[dict[str, Any]] | None:
    """Search YouTube for travel-related videos.

    Returns a list of lightweight video descriptors (id, title, channel,
    thumbnail, published_at) or ``None`` when the API key is missing / quota
    exhausted.  Cached for 12 h.
    """
    api_key = await vault.secret_for("youtube")
    if not api_key:
        logger.debug("No YouTube credential in the vault — skipping video search")
        return None

    async def fetch() -> list[dict[str, Any]] | None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                SEARCH_URL,
                params={
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "maxResults": max_results,
                    "order": order,
                    "key": api_key,
                },
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            return [
                {
                    "video_id": item["id"]["videoId"],
                    "title": item["snippet"]["title"],
                    "channel": item["snippet"]["channelTitle"],
                    "thumbnail": item["snippet"]["thumbnails"]["medium"]["url"],
                    "published_at": item["snippet"]["publishedAt"],
                }
                for item in items
            ]

    try:
        return await cached(
            f"youtube:search:{query.lower()}:{max_results}",
            fetch,
            ttl=settings.cache_ttl_long,
        )
    except Exception as exc:  # noqa: BLE001 — a missing video list never breaks a plan
        logger.warning("YouTube search failed for '%s': %s", query, exc)
    return None


async def video_stats(video_ids: list[str]) -> list[dict[str, Any]] | None:
    """Retrieve view/like counts for a list of video IDs.

    Cached for 6 h.  Returns ``None`` on failure.
    """
    api_key = await vault.secret_for("youtube")
    if not api_key or not video_ids:
        return None

    ids = ",".join(video_ids[:10])  # API allows max 50, keep conservative

    async def fetch() -> list[dict[str, Any]] | None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                VIDEOS_URL,
                params={
                    "part": "statistics",
                    "id": ids,
                    "key": api_key,
                },
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            return [
                {
                    "video_id": item["id"],
                    "view_count": int(item["statistics"].get("viewCount", 0)),
                    "like_count": int(item["statistics"].get("likeCount", 0)),
                }
                for item in items
            ]

    try:
        return await cached(
            f"youtube:stats:{ids}",
            fetch,
            ttl=settings.cache_ttl_short,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("YouTube video_stats failed: %s", exc)
    return None
