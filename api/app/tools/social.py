"""Social-media → trip seed (Phase: plan from a post, any platform).

Turns a social-media post into a structured trip seed the agents can plan from.
"Any platform" means we accept whatever the traveller can give us and degrade
gracefully:

- a **URL** (YouTube/TikTok/Instagram/X/Facebook/blog) → YouTube transcript, then
  a best-effort Camofox crawl, then a DuckDuckGo lookup for the caption (IG/TikTok
  are bot-walled, so the search snippet is the reliable path);
- pasted **text** (the caption itself) → the most robust input, always works;
- a **screenshot image** of a post → the vision model reads the places off it
  (reuses the assistant's vision model).

An LLM then distils the gathered content into {destination, places, vibe,
duration, month, goal} — `goal` is a natural-language trip request the existing
plan pipeline consumes unchanged.
"""

from __future__ import annotations

import asyncio
import html as _html
import json
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.core import llm
from app.core.cache import cached
from app.core.settings import settings
from app.core.text import scrub_surrogates
from app.tools import camofox

#: Public, keyless oEmbed endpoints — they return the post's title/caption +
#: author even when the page itself is bot-walled. This is the reliable way to
#: read a TikTok or YouTube caption.
_OEMBED = {
    "tiktok": "https://www.tiktok.com/oembed?url=",
    "youtube": "https://www.youtube.com/oembed?format=json&url=",
}

#: Platforms whose video/post page is JS-walled: a raw crawl returns only site
#: chrome + unrelated recommended posts, which makes the model plan the WRONG
#: trip. For these we trust the caption (oEmbed / Open Graph), never the crawl.
_SOCIAL_PLATFORMS = {"tiktok", "instagram", "x", "facebook"}

#: A real browser UA so share-link redirects resolve and link-preview meta tags
#: are served (many sites gate these behind a non-bot UA).
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

logger = logging.getLogger("journava")


def _client(timeout: float = 15.0) -> httpx.AsyncClient:
    """An HTTP client for caption fetches. Routes through the configured proxy
    when set — a rotating/residential IP is the only real fix for an IP-based
    rate-limit on a keyless endpoint like TikTok's oEmbed."""
    kwargs: dict[str, Any] = {
        "timeout": timeout,
        "follow_redirects": True,
        "headers": {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"},
    }
    if settings.camofox_proxy:
        kwargs["proxy"] = settings.camofox_proxy
    return httpx.AsyncClient(**kwargs)

_SEED_SYSTEM = """You turn social-media travel content into a structured trip \
seed. Read the post text / transcript / image description below and infer where \
the creator went and what they did. Name real places when you can.

The CAPTION and #hashtags are the primary signal for the destination — trust \
them. IGNORE anything that looks like site navigation, menus, "For You", \
"Following", cookie banners, or unrelated recommended videos: those are the app's \
own chrome, not this post. If the real post is about place A, do not let a \
recommended clip about place B change your answer.

Respond ONLY as JSON:
{"destination": "primary city or country", "cities": ["..."],
 "places": [{"name": "specific place/restaurant/landmark", "kind": "food|sight|activity|hotel|area"}],
 "vibe": "e.g. foodie, nature, nightlife, budget backpacking, luxury, family",
 "duration_days": number|null, "month": "month name"|null, "origin_hint": "city/IATA"|null,
 "goal": "one natural-language trip request naming the destination, 3-5 of the places, the vibe and duration"}

If the content isn't about a travel destination, set destination to "" and goal to ""."""

_IMAGE_SYSTEM = "You identify travel content in an image for a trip planner."


def _platform(url: str) -> str:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u:
        return "instagram"
    if "twitter.com" in u or "x.com" in u:
        return "x"
    if "facebook.com" in u or "fb.watch" in u:
        return "facebook"
    return "web"


async def _oembed(url: str, platform: str) -> str:
    """Fetch the post's caption/title via the platform's public oEmbed API.

    The caption is the ground truth for a walled post, so it's worth a couple of
    retries — TikTok's oEmbed occasionally 429s/blips and clears on a short wait.
    """
    endpoint = _OEMBED.get(platform)
    if not endpoint:
        return ""
    for attempt in range(3):
        try:
            async with _client() as client:
                resp = await client.get(endpoint + quote(url, safe=""))
            if resp.status_code == 200:
                data = resp.json()
                bits = [str(data.get(k, "")) for k in ("title", "author_name", "description") if data.get(k)]
                if bits:
                    return " · ".join(bits)
            elif resp.status_code not in (400, 404):  # transient (429/5xx) → retry
                await asyncio.sleep(0.6 * (attempt + 1))
                continue
            break  # 200-but-empty or a hard 400/404 won't improve on retry
        except Exception as exc:  # noqa: BLE001
            logger.info("oembed attempt %d failed (%s): %s", attempt + 1, platform, exc)
            await asyncio.sleep(0.5)
    return ""


async def _resolve_url(url: str) -> str:
    """Follow redirects so a share link (vm.tiktok.com/…, tiktok.com/t/…,
    instagr.am/…) becomes the canonical URL that oEmbed and meta scraping accept.
    Returns the final URL and the page HTML if we happened to fetch it."""
    try:
        async with _client(timeout=12.0) as client:
            resp = await client.get(url)
            return str(resp.url)
    except Exception as exc:  # noqa: BLE001
        logger.info("url resolve failed: %s", exc)
        return url


def _parse_meta(html_text: str) -> dict[str, str]:
    """Pull `<meta property/name … content …>` pairs regardless of attr order."""
    metas: dict[str, str] = {}
    for tag in re.findall(r"<meta\b[^>]*>", html_text, re.I):
        key = re.search(r"(?:property|name)\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
        val = re.search(r"content\s*=\s*[\"']([^\"']*)[\"']", tag, re.I | re.S)
        if key and val:
            metas[key.group(1).lower()] = _html.unescape(val.group(1))
    return metas


async def _og_meta(url: str) -> str:
    """The post's caption from Open Graph / Twitter-card meta tags, which sites
    serve for link previews even when the app itself is JS-walled (reliable for
    Instagram / X / blogs; TikTok serves an empty shell here, hence oEmbed)."""
    try:
        async with _client() as client:
            resp = await client.get(url)
        if resp.status_code != 200 or not resp.text:
            return ""
        metas = _parse_meta(resp.text)
        bits = [
            metas.get(k, "")
            for k in ("og:title", "og:description", "twitter:title", "twitter:description", "description")
            if metas.get(k)
        ]
        # De-duplicate while preserving order (og:title often == twitter:title).
        seen: set[str] = set()
        uniq = [b for b in bits if not (b in seen or seen.add(b))]
        return " · ".join(uniq)
    except Exception as exc:  # noqa: BLE001
        logger.info("og meta fetch failed: %s", exc)
    return ""


async def _gather_from_url(url: str) -> tuple[str, str]:
    """Best-effort content for a URL. Returns (text, platform).

    The order matters: the caption (oEmbed / Open Graph) is the ground truth for
    a walled social post. We deliberately do NOT crawl a social video page —
    that returns the app's navigation and unrelated recommended clips, which made
    the planner hallucinate a different destination. A raw crawl is used only for
    open web pages (blogs), whose body text really is the article.

    The whole gather is cached per URL for 12h: the same link never re-hits the
    upstream API, which is what actually stops the rate-limit (repeat submissions,
    the assistant + the plan box, and re-plans all share one fetch). Failures
    return None so a transient blip is never cached.
    """

    async def _do() -> dict[str, str] | None:
        platform = _platform(url)
        resolved = await _resolve_url(url) if platform in _SOCIAL_PLATFORMS else url
        if _platform(resolved) != "web":
            platform = _platform(resolved)  # a share link resolved to its real host
        parts: list[str] = []

        # 1) Caption via oEmbed (TikTok/YouTube), on the resolved then raw URL.
        caption = await _oembed(resolved, platform) or await _oembed(url, _platform(url))
        if caption:
            parts.append(f"[{platform} caption] {caption}")

        # 2) Open Graph / Twitter-card caption (Instagram / X / blogs).
        og = await _og_meta(resolved)
        if og and og not in caption:
            parts.append(f"[post] {og}")

        # 3) YouTube: the transcript is the actual video content — keep it.
        if platform == "youtube":
            try:
                tr = await camofox.youtube_transcript(resolved)
                if tr and tr.get("transcript"):
                    parts.append(str(tr["transcript"])[:6000])
            except Exception as exc:  # noqa: BLE001
                logger.info("youtube transcript failed: %s", exc)

        # 4) Open web (blog/article): the page body is the content — crawl it.
        #    Never for the walled social platforms (see docstring).
        if platform not in _SOCIAL_PLATFORMS and platform != "youtube":
            try:
                snap = await camofox.browse(resolved, attempts=3, respect_robots=True)
                if snap:
                    parts.append(snap[:6000])
            except Exception as exc:  # noqa: BLE001
                logger.info("web crawl failed: %s", exc)

        # 5) Last resort — a search on the URL sometimes surfaces the caption.
        if sum(len(p) for p in parts) < 60:
            try:
                snap2 = await camofox.search(url)
                if snap2:
                    parts.append(snap2[:3000])
            except Exception as exc:  # noqa: BLE001
                logger.info("social search fallback failed: %s", exc)

        text = "\n\n".join(parts).strip()
        # Return None on a failed/empty gather so `cached` doesn't store a miss.
        return {"text": text, "platform": platform} if len(text) >= 40 else None

    try:
        data = await cached(f"social:gather:{url}", _do, ttl=12 * 3600)
    except Exception as exc:  # noqa: BLE001
        logger.info("social gather failed: %s", exc)
        data = None
    if not data:
        return "", _platform(url)
    return data["text"], data["platform"]


async def _describe_image(image_data_url: str) -> str:
    msgs = [
        {"role": "system", "content": _IMAGE_SYSTEM},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "This is a screenshot of a social-media travel post. What place(s), "
                        "city/country, landmarks, food or activities does it show? Name them specifically."
                    ),
                },
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]
    try:
        return await llm.complete(msgs, model=settings.llm_vision_model, agent="assistant")
    except Exception as exc:  # noqa: BLE001
        logger.info("social image describe failed: %s", exc)
        return ""


async def _llm_seed(content: str) -> dict[str, Any]:
    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": _SEED_SYSTEM},
                {"role": "user", "content": content[:12_000]},
            ],
            response_format={"type": "json_object"},
            agent="assistant",
        )
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError("seed not an object")
    except Exception as exc:  # noqa: BLE001
        logger.warning("social seed extract failed: %s", exc)
        return {}
    places = [p for p in data.get("places", []) if isinstance(p, dict) and p.get("name")][:12]
    return {
        "destination": str(data.get("destination") or "").strip(),
        "cities": [str(c) for c in data.get("cities", []) if c][:8],
        "places": places,
        "vibe": str(data.get("vibe") or "").strip(),
        "duration_days": data.get("duration_days") if isinstance(data.get("duration_days"), int) else None,
        "month": str(data.get("month") or "").strip() or None,
        "origin_hint": str(data.get("origin_hint") or "").strip() or None,
        "goal": str(data.get("goal") or "").strip(),
    }


async def extract_trip_seed(
    *,
    url: str | None = None,
    text: str | None = None,
    image: str | None = None,
) -> dict[str, Any]:
    """Gather content from whatever the traveller gave us and distil a trip seed."""
    content = ""
    source_kind = "text"
    source_url: str | None = None

    if text and text.strip():
        content += text.strip()[:6000]
        source_kind = "text"
    if image:
        desc = await _describe_image(image)
        if desc:
            content += f"\n\n[image] {desc}"
            source_kind = "image"
    if url and url.strip():
        gathered, platform = await _gather_from_url(url.strip())
        content += f"\n\n{gathered}"
        source_kind = platform
        source_url = url.strip()

    content = content.strip()
    if len(content) < 20:
        return {"error": "Couldn't read enough from that source. Paste the caption or a screenshot instead."}

    seed = await _llm_seed(content)
    if not seed.get("destination") and not seed.get("goal"):
        return {"error": "That didn't look like a travel post — I couldn't find a destination."}

    seed["source_kind"] = source_kind
    seed["source_url"] = source_url
    seed["gathered_chars"] = len(content)
    # oEmbed captions bypass the Camofox scrub, so a mangled character can leave a
    # lone surrogate in the goal — strip it or the plan job 500s on JSON encode.
    return scrub_surrogates(seed)
