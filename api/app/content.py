"""Generative trip content — turn a planned trip into shareable stories.

Fills hackathon direction 08 (Generative content): an agent that reads the
trip's real destination, itinerary and picks and writes a shareable travel story
plus ready-to-post captions and hashtags for each platform. The inverse of
social ingestion (`tools/social.py`) — we read posts in, now we generate them
out, grounded in the actual plan rather than generic filler.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.brain import trip_store
from app.core import llm
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/content", tags=["content"])


class StoryRequest(BaseModel):
    results: dict[str, Any] | None = None
    tone: str = "warm"  # warm | punchy | luxe | adventurous


_SYSTEM = """You are Journava's Travel Storyteller. From a real trip plan, write \
shareable content the traveller can post. Ground it in the actual destination, \
days, places and food in the plan — name real spots, don't invent a different \
trip. Keep it authentic and specific, not brochure filler.

Respond ONLY as JSON:
{"title": "a catchy 3-6 word title",
 "story": "2-3 short vivid paragraphs (~110 words) in the requested tone",
 "captions": [
    {"platform": "instagram", "text": "caption with 1-2 emojis"},
    {"platform": "tiktok", "text": "hook-style caption"},
    {"platform": "x", "text": "<=200 char post"}
 ],
 "hashtags": ["#...", "..."]}"""


def _brief(res: dict[str, Any]) -> dict[str, Any]:
    chief = (res.get("chief") or {}).get("data") or {}
    research = (res.get("research") or {}).get("options") or []
    items = (res.get("itinerary") or {}).get("items") or []
    places = [o.get("title") for o in research if o.get("kind") == "activity"][:6]
    food = [o.get("title") for o in research if o.get("kind") == "restaurant"][:5]
    day_titles = [i.get("title") for i in items if i.get("kind") in ("activity", "meal")][:10]
    return {
        "destination": chief.get("destination"),
        "days": len({i.get("day_index") for i in items}) or None,
        "travellers": chief.get("travellers"),
        "interests": chief.get("goal"),
        "places": places,
        "food": food,
        "itinerary_highlights": day_titles,
    }


@router.post("/story")
async def story(body: StoryRequest, request: Request) -> dict[str, Any]:
    """Generate a shareable story + captions + hashtags from the trip."""
    res = body.results or (await trip_store.load_trip_durable() or {})
    if not res:
        return {"error": "No trip to write about yet."}
    brief = _brief(res)
    if not brief.get("destination"):
        return {"error": "Plan a trip first, then I'll write it up."}
    tone = body.tone if body.tone in ("warm", "punchy", "luxe", "adventurous") else "warm"

    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Tone: {tone}\nTrip:\n{json.dumps(brief, default=str)[:4000]}"},
            ],
            response_format={"type": "json_object"},
            agent="assistant",
        )
        data = json.loads(raw)
        if not isinstance(data, dict) or not data.get("story"):
            raise ValueError("empty story")
    except Exception as exc:  # noqa: BLE001
        logger.info("content story failed: %s", exc)
        return {"error": "Couldn't write the story right now — try again."}

    data["destination"] = brief["destination"]
    return {"content": data}
