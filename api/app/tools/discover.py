"""Shared web-discovery helpers — real research + citable sources for any agent.

The flagship agents (flight, hotel, research) crawl the web with Camofox and cite
their sources. These helpers let the lighter enrichment agents (transport,
shopping, …) do the same cheaply: ground their answer in a live crawl and attach
source links + TikTok embeds instead of answering from the model's memory alone.

Everything degrades to empty on failure — an agent that can't reach Camofox still
returns its LLM answer, just without sources.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.tools import camofox

logger = logging.getLogger(__name__)


async def crawl_sources(queries: list[str], *, max_sources: int = 6) -> dict[str, Any]:
    """Crawl each query with Camofox; return merged readable text + source URLs.

    Returns {"text": <excerpt for grounding the LLM>, "sources": [url, ...]}.
    """
    if not queries:
        return {"text": "", "sources": []}
    try:
        if not await camofox.available():
            return {"text": "", "sources": []}
    except Exception:  # noqa: BLE001 — availability probe is best-effort
        return {"text": "", "sources": []}

    results = await asyncio.gather(
        *(camofox.search_with_sources(q) for q in queries),
        return_exceptions=True,
    )
    texts: list[str] = []
    urls: list[str] = []
    seen: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            continue
        snapshot = (result.get("snapshot") or "")[:1500]
        if snapshot:
            texts.append(snapshot)
        for url in result.get("sources") or []:
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return {"text": "\n\n".join(texts)[:4000], "sources": urls[:max_sources]}


def source_links(urls: list[str]) -> list[dict[str, str]]:
    """Turn raw URLs into [{title, url}] where title is the (display-friendly) host."""
    out: list[dict[str, str]] = []
    for url in urls:
        match = re.match(r"https?://([^/]+)", url)
        host = (match.group(1) if match else url).replace("www.", "")
        out.append({"title": host, "url": url})
    return out


async def tiktok_reviews(query: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """Best-effort public TikTok clips for a topic, as official iframe-player embeds.

    TikTok's own search is bot-walled, but DuckDuckGo lists public
    `tiktok.com/@user/video/{id}` links Camofox can read. Returns objects shaped
    for the frontend `VideoReview` type. Empty on any failure (strictly optional).
    """
    try:
        if not await camofox.available():
            return []
        result = await camofox.search_with_sources(
            f"{query} site:tiktok.com", macro="@duckduckgo_search"
        )
        snapshot = (result or {}).get("snapshot") or ""
        sources = (result or {}).get("sources") or []
        haystack = snapshot + " " + " ".join(sources)

        seen: dict[str, str] = {}
        for path, vid in re.findall(r"(tiktok\.com/@[\w.-]+/video/(\d{6,}))", haystack):
            seen.setdefault(vid, f"https://www.{path}")
        for vid in re.findall(r"tiktok\.com/(?:embed|video|v)/(\d{6,})", haystack):
            seen.setdefault(vid, f"https://www.tiktok.com/embed/v2/{vid}")

        return [
            {
                "platform": "tiktok",
                "id": vid,
                "title": "TikTok review",
                "thumbnail": None,
                "views": 0,
                "embed_url": f"https://www.tiktok.com/player/v1/{vid}?music_info=1&description=1",
                "watch_url": watch,
            }
            for vid, watch in list(seen.items())[:limit]
        ]
    except Exception as exc:  # noqa: BLE001 — TikTok is strictly best-effort
        logger.debug("TikTok lookup failed for '%s': %s", query, exc)
        return []
