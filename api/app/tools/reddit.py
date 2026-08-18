"""Reddit API tool — traveler sentiment + recent tips (spec §9).

Used by the Research Agent to surface real traveler sentiment, recent
complaints, and hidden gems from relevant subreddits (r/travel,
r/solotravel, r/backpacking, destination-specific subs).

Free tier: 100 requests/min (OAuth), 10 requests/min (no auth).
Cache aggressively (12h) — Reddit content changes slowly.

Endpoint: https://oauth.reddit.com (authenticated)
          https://www.reddit.com/.json (public, rate-limited)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger(__name__)

REDDIT_JSON_URL = "https://www.reddit.com"
TIMEOUT = httpx.Timeout(15.0)

# Subreddits relevant to travel intelligence
TRAVEL_SUBS = ["travel", "solotravel", "backpacking", "digitalnomad"]


async def search(
    query: str,
    *,
    subreddit: str | None = None,
    sort: str = "relevance",
    limit: int = 10,
    time_filter: str = "year",
) -> list[dict[str, Any]] | None:
    """Search Reddit for traveler tips and sentiment.

    Uses the public `.json` endpoint (no OAuth needed for read-only search).
    Returns lightweight post descriptors or ``None`` on failure.
    Cached for 12 h.
    """

    async def fetch() -> list[dict[str, Any]] | None:
        sub = f"r/{subreddit}" if subreddit else "r+travel+solotravel+backpacking"
        url = f"{REDDIT_JSON_URL}/{sub}/search.json"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                url,
                params={
                    "q": query,
                    "sort": sort,
                    "limit": limit,
                    "t": time_filter,
                    "restrict_sr": "on" if subreddit else "off",
                },
                headers={"User-Agent": "Journava/1.0 (travel research agent)"},
            )
            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])
            return [
                {
                    "title": p["data"].get("title", ""),
                    "subreddit": p["data"].get("subreddit", ""),
                    "score": p["data"].get("score", 0),
                    "num_comments": p["data"].get("num_comments", 0),
                    "url": f"https://reddit.com{p['data'].get('permalink', '')}",
                    "selftext": (p["data"].get("selftext") or "")[:500],
                    "created_utc": p["data"].get("created_utc", 0),
                }
                for p in posts
                if not p["data"].get("stickied")
            ]

    cache_key = f"reddit:search:{query.lower()}:{subreddit or 'multi'}:{limit}"
    try:
        return await cached(cache_key, fetch, ttl=settings.cache_ttl_long)
    except Exception as exc:  # noqa: BLE001 — sentiment is nice-to-have
        logger.warning("Reddit search failed for '%s': %s", query, exc)
    return None


async def hot_posts(
    subreddit: str = "travel",
    *,
    limit: int = 5,
) -> list[dict[str, Any]] | None:
    """Fetch currently hot posts from a travel subreddit.

    Useful for detecting trending destinations or emerging travel concerns.
    Cached for 6 h.
    """

    async def fetch() -> list[dict[str, Any]] | None:
        url = f"{REDDIT_JSON_URL}/r/{subreddit}/hot.json"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                url,
                params={"limit": limit},
                headers={"User-Agent": "Journava/1.0 (travel research agent)"},
            )
            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])
            return [
                {
                    "title": p["data"].get("title", ""),
                    "score": p["data"].get("score", 0),
                    "num_comments": p["data"].get("num_comments", 0),
                    "url": f"https://reddit.com{p['data'].get('permalink', '')}",
                }
                for p in posts
                if not p["data"].get("stickied")
            ]

    try:
        return await cached(
            f"reddit:hot:{subreddit}:{limit}",
            fetch,
            ttl=settings.cache_ttl_short,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Reddit hot_posts failed for r/%s: %s", subreddit, exc)
    return None
