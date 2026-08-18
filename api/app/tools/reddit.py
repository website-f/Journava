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
import time
from typing import Any

import httpx

from app.core import vault
from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger(__name__)

REDDIT_JSON_URL = "https://www.reddit.com"
REDDIT_OAUTH_URL = "https://oauth.reddit.com"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
TIMEOUT = httpx.Timeout(15.0)

#: Reddit blocks unauthenticated datacenter traffic with 403, so a descriptive
#: UA is mandatory and OAuth is strongly preferred (see `_get_token`).
USER_AGENT = "web:journava:1.0 (travel research agent)"

# Subreddits relevant to travel intelligence
TRAVEL_SUBS = ["travel", "solotravel", "backpacking", "digitalnomad"]

_token: str | None = None
_token_expiry: float = 0.0


async def _get_token() -> str | None:
    """Fetch an app-only OAuth token, cached until shortly before expiry.

    Reddit now answers `403 Blocked` to unauthenticated requests from most
    hosting providers, so the public `.json` endpoints only work reliably from a
    residential IP. Returns None when credentials aren't configured, and the
    caller falls back to the public endpoint.
    """
    global _token, _token_expiry  # noqa: PLW0603

    resolved = await vault.resolve("reddit")
    if not resolved:
        return None
    client_secret = resolved.get("secret")
    client_id = (resolved.get("extra") or {}).get("client_id") or getattr(
        settings, "reddit_client_id", None
    )
    if not client_id or not client_secret:
        return None

    if _token and time.time() < _token_expiry - 60:
        return _token

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                REDDIT_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            body = resp.json()
            _token = body["access_token"]
            _token_expiry = time.time() + body.get("expires_in", 3600)
            return _token
    except Exception as exc:  # noqa: BLE001 — sentiment is nice-to-have
        logger.info("Reddit OAuth unavailable: %s", exc)
        return None


async def _request(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """GET a Reddit endpoint, preferring OAuth and falling back to public JSON."""
    token = await _get_token()
    attempts: list[tuple[str, dict[str, str]]] = []
    if token:
        attempts.append(
            (
                f"{REDDIT_OAUTH_URL}{path}",
                {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
            )
        )
    attempts.append((f"{REDDIT_JSON_URL}{path}.json", {"User-Agent": USER_AGENT}))

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for url, headers in attempts:
            try:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                # 401/403 on the OAuth attempt is worth retrying unauthenticated;
                # anything else means this path simply has nothing for us.
                logger.info("Reddit %s returned %s", url, exc.response.status_code)
                continue
            except Exception as exc:  # noqa: BLE001
                logger.info("Reddit request to %s failed: %s", url, exc)
                continue
    return None


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
        # Multireddit syntax needs `+`-joined names, not the `r+` typo that made
        # every unscoped search hit a subreddit literally called "r+travel+…".
        sub = subreddit or "+".join(TRAVEL_SUBS)
        data = await _request(
            f"/r/{sub}/search",
            {
                "q": query,
                "sort": sort,
                "limit": limit,
                "t": time_filter,
                "restrict_sr": "on" if subreddit else "off",
            },
        )
        if not data:
            return None
        posts = data.get("data", {}).get("children", [])
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
        data = await _request(f"/r/{subreddit}/hot", {"limit": limit})
        if not data:
            return None
        posts = data.get("data", {}).get("children", [])
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
