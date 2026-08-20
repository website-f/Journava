"""Personalized recommendations for the home screen.

Reads the traveller's own history (past runs) and turns it into "pick up where
you left off" cards, then fills the rest with a few strong starters so a brand-new
account still has somewhere to go. Gnosion-derived route memories can enrich this
later; history is the honest first signal and needs no extra plumbing.
"""

from __future__ import annotations

import logging
from typing import Any

from app.brain import history

logger = logging.getLogger(__name__)

#: Fallbacks for an empty account — each maps to a real scope slug (graph/scopes).
_STARTERS: list[dict[str, Any]] = [
    {
        "kind": "starter",
        "title": "Find the cheapest flights",
        "subtitle": "Live fares for any route and date",
        "scope": "flights_only",
        "icon": "flight",
    },
    {
        "kind": "starter",
        "title": "Plan a full trip",
        "subtitle": "Flights, stays and a day-by-day itinerary",
        "scope": "full_trip",
        "icon": "trip",
    },
    {
        "kind": "starter",
        "title": "Discover a destination",
        "subtitle": "Reviews, crowds and halal-friendly food",
        "scope": "food",
        "icon": "explore",
    },
    {
        "kind": "starter",
        "title": "Check entry requirements",
        "subtitle": "Visa, passport and advisories before booking",
        "scope": "entry",
        "icon": "visa",
    },
]


#: "You liked X → try Y" — similar destinations by vibe/region, so a Japan trip
#: nudges Korea/Taiwan next. Keys are matched (word-boundary) in past goals.
_SIMILAR: dict[str, list[str]] = {
    "japan": ["South Korea", "Taiwan"],
    "korea": ["Japan", "Taiwan"],
    "south korea": ["Japan", "Taiwan"],
    "taiwan": ["Japan", "Hong Kong"],
    "thailand": ["Vietnam", "Bali"],
    "vietnam": ["Thailand", "Cambodia"],
    "bali": ["Lombok", "Thailand"],
    "indonesia": ["Thailand", "Malaysia"],
    "singapore": ["Hong Kong", "Malaysia"],
    "malaysia": ["Thailand", "Singapore"],
    "kota kinabalu": ["Langkawi", "Bali"],
    "china": ["Hong Kong", "Taiwan"],
    "hong kong": ["Taiwan", "Macau"],
    "australia": ["New Zealand", "Fiji"],
    "united kingdom": ["Ireland", "France"],
    "uk": ["Ireland", "France"],
    "france": ["Italy", "Spain"],
    "italy": ["Greece", "Spain"],
    "turkey": ["Greece", "Georgia"],
    "uae": ["Qatar", "Oman"],
    "dubai": ["Abu Dhabi", "Qatar"],
    "brazil": ["Argentina", "Peru"],
}


def _similar_cards(entries: list[dict[str, Any]], seen: set[str]) -> list[dict[str, Any]]:
    """Turn recent destinations into 'you liked X, try Y' suggestions."""
    import re

    out: list[dict[str, Any]] = []
    used_targets: set[str] = set()
    for entry in entries:
        text = ((entry.get("destination") or "") + " " + (entry.get("goal") or "")).lower()
        for key, targets in _SIMILAR.items():
            if re.search(rf"\b{re.escape(key)}\b", text):
                for target in targets:
                    tkey = target.lower()
                    if tkey in used_targets:
                        continue
                    used_targets.add(tkey)
                    out.append(
                        {
                            "kind": "similar",
                            "title": f"Try {target}",
                            "subtitle": f"Similar vibe to {key.title()} — based on your trips",
                            "scope": "full_trip",
                            "goal": f"Plan a trip to {target}",
                            "icon": "explore",
                        }
                    )
                break
    return out


async def build(user_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    seen: set[str] = set()

    try:
        entries = await history.list_entries(limit=15)
    except Exception as exc:  # noqa: BLE001 — recommendations never break the home
        logger.debug("recommendations: history read failed: %s", exc)
        entries = []

    for entry in entries:
        goal = (entry.get("goal") or "").strip()
        if not goal:
            continue
        key = goal.lower()[:48]
        if key in seen:
            continue
        seen.add(key)
        recs.append(
            {
                "id": entry.get("id"),
                "kind": "recent",
                "title": goal[:90],
                "subtitle": "Pick up where you left off",
                "scope": entry.get("scope") or "full_trip",
                "goal": goal,
                "icon": "history",
            }
        )
        if len(recs) >= limit:
            break

    # "Because you explored Japan, try Korea" — placed after the recents.
    for card in _similar_cards(entries, seen):
        if len(recs) >= limit:
            break
        recs.append({**card})

    for starter in _STARTERS:
        if len(recs) >= limit:
            break
        recs.append({**starter, "goal": ""})

    return recs[:limit]
