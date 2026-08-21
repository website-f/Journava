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

import json
import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.core import llm
from app.core.settings import settings
from app.tools import camofox

#: Public, keyless oEmbed endpoints — they return the post's title/caption +
#: author even when the page itself is bot-walled. This is the reliable way to
#: read a TikTok or YouTube caption.
_OEMBED = {
    "tiktok": "https://www.tiktok.com/oembed?url=",
    "youtube": "https://www.youtube.com/oembed?format=json&url=",
}

logger = logging.getLogger("journava")

_SEED_SYSTEM = """You turn social-media travel content into a structured trip \
seed. Read the post text / transcript / image description below and infer where \
the creator went and what they did. Name real places when you can.

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
    """Fetch the post's caption/title via the platform's public oEmbed API."""
    endpoint = _OEMBED.get(platform)
    if not endpoint:
        return ""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(endpoint + quote(url, safe=""))
        if resp.status_code == 200:
            data = resp.json()
            bits = [str(data.get(k, "")) for k in ("title", "author_name", "description") if data.get(k)]
            return " · ".join(bits)
    except Exception as exc:  # noqa: BLE001
        logger.info("oembed failed (%s): %s", platform, exc)
    return ""


async def _gather_from_url(url: str) -> tuple[str, str]:
    """Best-effort content for a social URL. Returns (text, platform)."""
    platform = _platform(url)
    parts: list[str] = []

    # oEmbed first — it's the reliable caption source for TikTok / YouTube.
    oembed = await _oembed(url, platform)
    if oembed:
        parts.append(f"[{platform} caption] {oembed}")

    if platform == "youtube":
        try:
            tr = await camofox.youtube_transcript(url)
            if tr and tr.get("transcript"):
                parts.append(str(tr["transcript"])[:6000])
        except Exception as exc:  # noqa: BLE001
            logger.info("youtube transcript failed: %s", exc)

    try:
        snap = await camofox.browse(url, attempts=3, respect_robots=True)
        if snap:
            parts.append(snap[:6000])
    except Exception as exc:  # noqa: BLE001
        logger.info("social crawl failed: %s", exc)

    # IG/TikTok/X pages are usually walled → the DDG snippet carries the caption.
    if sum(len(p) for p in parts) < 400:
        try:
            snap2 = await camofox.search(f"{url}")
            if snap2:
                parts.append(snap2[:4000])
        except Exception as exc:  # noqa: BLE001
            logger.info("social search fallback failed: %s", exc)

    return "\n\n".join(parts), platform


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
    return seed
