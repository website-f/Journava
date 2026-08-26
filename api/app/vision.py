"""AI camera — visual search + Discovery.

A traveller snaps a photo in the assistant's camera. `POST /vision/identify`:
1. A vision model names the subject (place / food / landmark / nature / object)
   and how sure it is.
2. If it's recognisable, Camofox pulls real references — and we always attach
   TikTok / YouTube / Instagram / News search links so there's something to watch
   and read. If the shot is blurry / generic / ambiguous, we say so plainly
   instead of inventing facts ("point at a place, food or landmark").

The traveller can then save the result to their Discovery page as a travel note.
Everything is scoped to the signed-in user.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core import db, llm
from app.core.settings import settings
from app.tools import discover

logger = logging.getLogger("journava")

router = APIRouter(prefix=settings.api_prefix, tags=["vision"])


def _user_id(request: Request) -> str | None:
    return (getattr(request.state, "auth", {}) or {}).get("sub")


class IdentifyRequest(BaseModel):
    image: str  # data URL or https URL


_VISION_SYSTEM = """You are a sharp visual-search engine for travellers (like \
Google Lens for trips). Identify the MAIN subject of the photo as specifically as \
you can — a named landmark/place, a dish, a drink, a plant/animal, or an object.

Respond ONLY as JSON:
{"name": "the most specific name you can ('Petronas Twin Towers', 'Nasi Lemak', \
'Shiba Inu') — not a generic label if you can name it",
 "category": "place|landmark|food|drink|nature|animal|art|object|other|unclear",
 "confidence": number 0-1,
 "description": "1-2 sentences on what it is",
 "search_query": "the best phrase to search the web/social for more",
 "facts": ["short interesting fact", ...up to 3]}
If the image is blurry, generic, a random object you can't place, or you're just \
guessing, set category to "unclear" and confidence below 0.4."""

async def _run_vision(content: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Identify via any configured vision-capable model (gateway picks one from
    the Engine pool). Returns parsed JSON, or None if no vision model succeeds."""
    try:
        raw = await llm.complete_vision(
            [{"role": "system", "content": _VISION_SYSTEM}, {"role": "user", "content": content}],
            response_format={"type": "json_object"}, agent="vision",
        )
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.info("vision identify unavailable: %s", exc)
        return None


def _social_links(query: str) -> list[dict[str, str]]:
    q = quote(query)
    qr = quote(query + " review")
    return [
        {"type": "video", "title": "YouTube reviews", "url": f"https://www.youtube.com/results?search_query={qr}"},
        {"type": "video", "title": "TikTok", "url": f"https://www.tiktok.com/search?q={q}"},
        {"type": "social", "title": "Instagram", "url": f"https://www.instagram.com/explore/search/keyword/?q={q}"},
        {"type": "news", "title": "In the news", "url": f"https://news.google.com/search?q={q}"},
    ]


@router.post("/vision/identify")
async def identify(body: IdentifyRequest, request: Request) -> dict[str, Any]:
    """Vision identify + Camofox references. Fast path (~vision + one crawl)."""
    if not body.image:
        return {"error": "No image."}
    content = [
        {"type": "text", "text": "Identify the main subject of this photo for a traveller."},
        {"type": "image_url", "image_url": {"url": body.image}},
    ]
    vision = await _run_vision(content)
    if vision is None:
        return {
            "is_random": True, "title": "Couldn't read that", "category": "unclear", "confidence": 0.0,
            "description": "I couldn't make out the photo — try again with better light and the subject centred.",
            "facts": [], "links": [],
        }

    name = str(vision.get("name") or "").strip()
    category = str(vision.get("category") or "unclear").lower()
    try:
        confidence = float(vision.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    description = str(vision.get("description") or "").strip()
    facts = [str(f) for f in (vision.get("facts") or [])][:3]
    query = str(vision.get("search_query") or name).strip() or name

    # Random / unsure — be honest rather than fabricate.
    if category == "unclear" or confidence < 0.4 or not name:
        return {
            "is_random": True,
            "title": name or "Not sure what this is",
            "category": "unclear",
            "confidence": round(confidence, 2),
            "description": description or "These look like random results — point the camera at a place, food, landmark, plant or object and I'll dig in.",
            "facts": facts,
            "links": [],
        }

    # Recognised. The TikTok/YouTube/Instagram/News links are instant search links
    # (so the result comes back fast, under ~10s — bounded by the vision call).
    # A short, capped Camofox crawl adds real article links when it's quick enough;
    # if it's slow we return immediately with the search links + the vision facts.
    links = _social_links(query)
    try:
        found = await asyncio.wait_for(
            discover.crawl_sources([f"{name} {category} review"], max_sources=3), timeout=2.5
        )
        for s in list(found.get("sources") or [])[:3]:
            links.append({"type": "web", "title": s.split("/")[2] if "://" in s else s, "url": s})
    except (Exception, TimeoutError) as exc:  # noqa: BLE001 — never block the result
        logger.info("vision crawl skipped (kept fast): %s", exc)

    return {
        "is_random": False,
        "title": name,
        "category": category,
        "confidence": round(confidence, 2),
        "description": description,
        "facts": facts,
        "links": links,
        "query": query,
    }


# --------------------------------------------------------------------------- #
# Discovery — saved travel notes
# --------------------------------------------------------------------------- #


class SaveDiscovery(BaseModel):
    image_url: str | None = None
    title: str
    category: str | None = None
    description: str | None = None
    facts: list[str] = []
    links: list[dict[str, str]] = []


def _row(r: dict[str, Any]) -> dict[str, Any]:
    def _j(v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (ValueError, TypeError):
                return []
        return v or []
    return {
        "id": str(r["id"]),
        "image_url": r.get("image_url"),
        "title": r.get("title"),
        "category": r.get("category"),
        "description": r.get("description"),
        "facts": _j(r.get("facts")),
        "links": _j(r.get("links")),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


@router.post("/discoveries")
async def save_discovery(body: SaveDiscovery, request: Request) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    uid = _user_id(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO discoveries (user_id, image_url, title, category, description, facts, links)
               VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
            uuid.UUID(uid) if uid else None,
            body.image_url, body.title[:160], (body.category or None),
            (body.description or None), json.dumps(body.facts[:6]), json.dumps(body.links[:12]),
        )
    return {"discovery": _row(dict(row))}


@router.get("/discoveries")
async def list_discoveries(request: Request) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"discoveries": []}
    uid = _user_id(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM discoveries WHERE (user_id = $1 OR $1 IS NULL) ORDER BY created_at DESC LIMIT 100",
            uuid.UUID(uid) if uid else None,
        )
    return {"discoveries": [_row(dict(r)) for r in rows]}


@router.delete("/discoveries/{discovery_id}")
async def delete_discovery(discovery_id: str, request: Request) -> dict[str, bool]:
    pool = await db.get_pool()
    if pool is None:
        return {"removed": False}
    uid = _user_id(request)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM discoveries WHERE id = $1 AND (user_id = $2 OR $2 IS NULL)",
            uuid.UUID(discovery_id), uuid.UUID(uid) if uid else None,
        )
    return {"removed": result.endswith("1")}
