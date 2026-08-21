"""Destination thumbnail — a real, heavily-compressed image for a trip card.

Finds a representative photo of a destination (Wikipedia/Wikimedia REST, keyless
and reliable), downloads it, and re-encodes it small with Pillow — a ~640px-wide
JPEG at q78, so a card thumbnail is ~15-40 KB with no visible quality loss.
Returned as a data URI so the card renders it with no extra storage or serving.
Cached per destination. Any failure returns None → the card keeps its colour band.
"""

from __future__ import annotations

import base64
import io
import logging
from urllib.parse import quote

import httpx

from app.core.cache import cached

logger = logging.getLogger("journava")

_UA = {"User-Agent": "Journava/1.0 (travel planner; contact@journava.test)"}
_WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"


async def _wiki_image_url(destination: str) -> str | None:
    """A representative image URL for the destination via Wikipedia's REST API."""
    # Try the full string, then the leading part ("Chengdu, China" -> "Chengdu").
    candidates = [destination.strip(), destination.split(",")[0].strip()]
    seen: set[str] = set()
    for q in candidates:
        if not q or q.lower() in seen:
            continue
        seen.add(q.lower())
        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers=_UA) as client:
                resp = await client.get(_WIKI_SUMMARY + quote(q))
            if resp.status_code == 200:
                data = resp.json()
                src = (data.get("originalimage") or data.get("thumbnail") or {}).get("source")
                if src:
                    return src
        except Exception as exc:  # noqa: BLE001
            logger.info("wiki image lookup failed for %s: %s", q, exc)
    return None


def _compress(data: bytes, *, width: int = 640, quality: int = 78) -> str | None:
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        if w > width:
            im = im.resize((width, max(1, round(h * width / w))))
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        logger.info("thumbnail compress failed: %s", exc)
        return None


async def _fetch(destination: str) -> str | None:
    url = await _wiki_image_url(destination)
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=_UA) as client:
            resp = await client.get(url)
        if resp.status_code != 200 or not resp.content:
            return None
    except Exception as exc:  # noqa: BLE001
        logger.info("thumbnail download failed: %s", exc)
        return None
    return _compress(resp.content)


async def thumbnail(destination: str) -> str | None:
    """A compressed data-URI thumbnail for the destination, or None. Cached 7 days."""
    if not destination or not destination.strip():
        return None
    try:
        return await cached(f"thumb:{destination.strip().lower()}", lambda: _fetch(destination), ttl=7 * 24 * 3600)
    except Exception as exc:  # noqa: BLE001
        logger.info("thumbnail cache path failed: %s", exc)
        return await _fetch(destination)
