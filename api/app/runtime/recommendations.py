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


async def build(user_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    recs: list[dict[str, Any]] = []
    seen: set[str] = set()

    try:
        entries = await history.list_entries(limit=10)
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

    for starter in _STARTERS:
        if len(recs) >= limit:
            break
        recs.append({**starter, "goal": ""})

    return recs[:limit]
