"""External tool integrations (spec §9).

Implemented tools (each follows: async httpx + `cached()` + graceful failure):
  - atlas_skill   — Atlas Flight Booking Skill CLI wrapper (flights, global scope)
  - open_meteo    — weather forecast, no key required
  - frankfurter   — FX rates, no key required
  - gdelt         — real-time global events/conflicts/disasters (risk detection)
  - rest_countries — country info (visa, languages, currency), no key required

Rules that apply to every tool in this package:
  1. Official API first, permitted public pages second, never bypass access controls.
  2. API = source of truth for structure; crawl = discovery + verification.
  3. Cache aggressively (Redis TTL 6–24h) to protect free quotas.
  4. A failing tool degrades the result, it never breaks the run.
"""

from app.tools import atlas_skill, open_meteo, frankfurter, gdelt, rest_countries, camofox

__all__ = ["atlas_skill", "open_meteo", "frankfurter", "gdelt", "rest_countries", "camofox"]
