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


#: Iconic destinations to surface to travellers who haven't searched them yet —
#: an eye-catching "for you" that's about DISCOVERY, not their own history.
_POPULAR: list[tuple[str, str]] = [
    ("Tokyo", "Neon nights, ancient temples and the world's best food"),
    ("Bali", "Rice terraces, surf breaks and beach clubs"),
    ("Istanbul", "Where Europe meets Asia — bazaars, mosques, Bosphorus"),
    ("Dubai", "Desert safaris, sky-high views and gold souks"),
    ("Paris", "Art, cafés and the Eiffel Tower at golden hour"),
    ("Seoul", "K-pop energy, palaces and midnight street food"),
    ("Bangkok", "Temples, floating markets and rooftop bars"),
    ("Doha", "Souq Waqif, Museum of Islamic Art and desert dunes"),
    ("Cappadocia", "Hot-air balloons over fairy-chimney valleys"),
    ("Kyoto", "Bamboo groves, geisha districts and zen gardens"),
    ("Santorini", "White-washed cliffs over a caldera sunset"),
]


async def build(user_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """A discovery-first 'for you': destinations the traveller has NOT searched
    yet — similar-to-their-trips first, then iconic places — each with a photo
    thumbnail so the home reads like a travel magazine, not a history log."""
    import asyncio

    from app.tools.photos import place_photo

    try:
        entries = await history.list_entries(limit=15)
    except Exception as exc:  # noqa: BLE001 — recommendations never break the home
        logger.debug("recommendations: history read failed: %s", exc)
        entries = []

    searched = " ".join(
        ((e.get("destination") or "") + " " + (e.get("goal") or "")).lower() for e in entries
    )

    cards: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(dest: str, subtitle: str, kind: str) -> None:
        dest = dest.strip()
        key = dest.lower()
        if not dest or key in seen or key in searched:
            return  # skip anything they've already searched
        seen.add(key)
        cards.append(
            {
                "kind": kind,
                "title": dest,
                "subtitle": subtitle,
                "scope": "full_trip",
                "goal": f"Plan a full trip to {dest}",
                "destination": dest,
                "icon": "explore",
            }
        )

    # 1) "You loved Japan → try Korea" — discovery grounded in their own trips.
    for card in _similar_cards(entries, seen):
        _add(card["title"].replace("Try ", ""), card["subtitle"], "similar")

    # 2) Iconic places they haven't looked at yet.
    for name, tagline in _POPULAR:
        if len(cards) >= limit:
            break
        if tagline:
            _add(name, tagline, "discover")

    cards = cards[:limit]

    # Resolve a photo thumbnail for each, in parallel (keyless Wikipedia lead
    # image; cached). A miss just leaves the card image-less.
    images = await asyncio.gather(
        *(place_photo(f"{c['destination']} travel landmark") for c in cards),
        return_exceptions=True,
    )
    for card, img in zip(cards, images):
        card["image"] = img if isinstance(img, str) else None

    # Brand-new account with no history still gets the starters as a fallback.
    if not cards:
        return [{**s, "goal": s.get("goal", "")} for s in _STARTERS][:limit]
    return cards
