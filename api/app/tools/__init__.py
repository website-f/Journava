"""External tool integrations (spec §9).

Implemented tools (each follows: async httpx + `cached()` + graceful failure):
  - atlas_skill   — Atlas Flight Booking Skill CLI wrapper (flights, global scope)
  - amadeus       — Amadeus Self-Service flight search + cheapest dates (secondary)
  - open_meteo    — weather forecast, no key required
  - frankfurter   — FX rates, no key required
  - gdelt         — real-time global events/conflicts/disasters (risk detection)
  - rest_countries — country info (visa, languages, currency), no key required
  - halal         — halal certification verification (JAKIM/MUIS/HalalTrip)
  - youtube       — YouTube Data API video search + stats (10k units/day free)
  - reddit        — Reddit traveler sentiment + trending posts (public JSON)
  - camofox       — stealth browser research (Google, Wikipedia, YouTube, Reddit)

Rules that apply to every tool in this package:
  1. Official API first, permitted public pages second, never bypass access controls.
  2. API = source of truth for structure; crawl = discovery + verification.
  3. Cache aggressively (Redis TTL 6–24h) to protect free quotas.
  4. A failing tool degrades the result, it never breaks the run.
"""

from app.tools import (
    amadeus,
    atlas_skill,
    camofox,
    frankfurter,
    gdelt,
    halal,
    open_meteo,
    reddit,
    rest_countries,
    youtube,
)

__all__ = [
    "atlas_skill",
    "amadeus",
    "open_meteo",
    "frankfurter",
    "gdelt",
    "rest_countries",
    "halal",
    "youtube",
    "reddit",
    "camofox",
]
