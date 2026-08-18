"""Camofox Browser client — stealth headless browser for real web research.

Wraps the REST API exposed by camofox-browser (port 9377). Supports:
  - Search macros: @google_search, @youtube_search, @reddit_search, @wikipedia_search
  - YouTube transcript extraction
  - Direct page browsing with accessibility snapshots

The Camofox engine is Camoufox — a Firefox fork with C++ anti-detection that
bypasses Cloudflare, fingerprinting, and bot detection. No API keys needed.

A failing crawl degrades the result (returns None); it never breaks the run.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

import httpx

from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
YOUTUBE_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

#: Consistent user identity for Camofox session isolation.
USER_ID = "journava"


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


#: Matches URLs inside an accessibility snapshot, so a crawled claim can always
#: be traced back to the page it came from.
_URL_PATTERN = re.compile(r"https?://[^\s\)\]\}\"'<>]+")

#: Hosts that are navigation rather than evidence — never cited as a source.
_NOISE_HOSTS = (
    "google.com/search",
    "google.com/preferences",
    "google.com/intl",
    "accounts.google.com",
    "policies.google.com",
    "support.google.com",
    "youtube.com/about",
    "youtube.com/t/",
    "reddit.com/login",
    "wikimediafoundation.org",
    "creativecommons.org",
    "mediawiki.org",
)


def extract_sources(snapshot: str, *, limit: int = 8) -> list[str]:
    """Pull the citable URLs out of a snapshot, in order, de-duplicated.

    Research that cannot be checked is not much better than a guess, so every
    crawl-derived option carries the page it came from.
    """
    seen: set[str] = set()
    urls: list[str] = []
    for raw in _URL_PATTERN.findall(snapshot or ""):
        url = raw.rstrip(".,;:!?”’")
        if url in seen:
            continue
        if any(noise in url for noise in _NOISE_HOSTS):
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


async def search_with_sources(
    query: str,
    macro: str = "@google_search",
) -> dict[str, Any] | None:
    """Run a search macro and return both the snapshot and its source URLs."""
    snapshot = await search(query, macro=macro)
    if not snapshot:
        return None
    return {
        "snapshot": snapshot,
        "sources": extract_sources(snapshot),
        "macro": macro,
        "query": query,
    }


async def search(query: str, macro: str = "@google_search") -> str | None:
    """Run a search macro and return the accessibility snapshot text.

    Args:
        query: The search query (e.g. "Tokyo halal travel guide").
        macro: One of @google_search, @youtube_search, @reddit_search,
               @wikipedia_search, @yelp_search, etc.

    Returns:
        The accessibility snapshot as plain text, or None on failure.
    """

    async def fetch() -> str | None:
        base = settings.camofox_url.rstrip("/")
        session_key = f"research-{uuid.uuid4().hex[:8]}"

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Create a tab with the search macro
            tab = await _create_tab(client, base, session_key, macro=macro, query=query)
            if tab is None:
                return None

            tab_id = tab["tabId"]
            try:
                snapshot = await _snapshot(client, base, tab_id)
                return snapshot
            finally:
                await _close_tab(client, base, tab_id)

    try:
        return await cached(f"camofox:search:{macro}:{query}", fetch, ttl=6 * 3600)
    except Exception:  # noqa: BLE001
        logger.warning("Camofox search failed: macro=%s query=%s", macro, query)
        return None


async def youtube_transcript(url: str, languages: list[str] | None = None) -> dict[str, Any] | None:
    """Extract captions from a YouTube video.

    Returns dict with keys: transcript, video_title, total_words.
    Returns None on failure.
    """

    async def fetch() -> dict[str, Any] | None:
        base = settings.camofox_url.rstrip("/")
        async with httpx.AsyncClient(timeout=YOUTUBE_TIMEOUT) as client:
            resp = await client.post(
                f"{base}/youtube/transcript",
                json={"url": url, "languages": languages or ["en"]},
            )
            if resp.status_code != 200:
                logger.debug("YouTube transcript HTTP %d for %s", resp.status_code, url)
                return None
            data = resp.json()
            if data.get("status") != "ok":
                return None
            return {
                "transcript": data.get("transcript", ""),
                "video_title": data.get("video_title", ""),
                "total_words": data.get("total_words", 0),
            }

    try:
        return await cached(f"camofox:yt:{url}", fetch, ttl=24 * 3600)
    except Exception:  # noqa: BLE001
        logger.warning("Camofox YouTube transcript failed: %s", url)
        return None


async def browse(url: str) -> str | None:
    """Navigate to a URL and return the accessibility snapshot.

    Returns the snapshot text, or None on failure.
    """

    async def fetch() -> str | None:
        base = settings.camofox_url.rstrip("/")
        session_key = f"browse-{uuid.uuid4().hex[:8]}"

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            tab = await _create_tab(client, base, session_key, url=url)
            if tab is None:
                return None

            tab_id = tab["tabId"]
            try:
                snapshot = await _snapshot(client, base, tab_id)
                return snapshot
            finally:
                await _close_tab(client, base, tab_id)

    try:
        return await cached(f"camofox:browse:{url}", fetch, ttl=6 * 3600)
    except Exception:  # noqa: BLE001
        logger.warning("Camofox browse failed: %s", url)
        return None


async def available() -> bool:
    """Check if the Camofox Browser service is reachable."""
    try:
        base = settings.camofox_url.rstrip("/")
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{base}/health")
            return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


async def _create_tab(
    client: httpx.AsyncClient,
    base: str,
    session_key: str,
    *,
    url: str | None = None,
    macro: str | None = None,
    query: str | None = None,
) -> dict[str, Any] | None:
    """Create a new tab. Returns {"tabId": "..."} or None."""
    body: dict[str, Any] = {"userId": USER_ID, "sessionKey": session_key}

    if macro and query:
        body["macro"] = macro
        body["query"] = query
    elif url:
        body["url"] = url
    else:
        return None

    try:
        resp = await client.post(f"{base}/tabs", json=body)
        if resp.status_code not in (200, 201):
            logger.debug("Camofox create tab HTTP %d", resp.status_code)
            return None
        data = resp.json()
        return {"tabId": data.get("tabId") or data.get("id")}
    except Exception:  # noqa: BLE001
        return None


async def _snapshot(
    client: httpx.AsyncClient,
    base: str,
    tab_id: str,
) -> str | None:
    """Get accessibility snapshot for a tab."""
    try:
        resp = await client.get(
            f"{base}/tabs/{tab_id}/snapshot",
            params={"userId": USER_ID},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("snapshot", "")
    except Exception:  # noqa: BLE001
        return None


async def _close_tab(
    client: httpx.AsyncClient,
    base: str,
    tab_id: str,
) -> None:
    """Close a tab (fire-and-forget cleanup)."""
    try:
        await client.delete(f"{base}/tabs/{tab_id}")
    except Exception:  # noqa: BLE001
        pass  # Best-effort cleanup
