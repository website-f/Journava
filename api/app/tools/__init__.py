"""External tool integrations (spec §9).

Implemented in Phase 0 as the reference shape:
  - atlas_skill  — Atlas Flight Booking Skill CLI wrapper (flights, global scope)
  - open_meteo   — weather forecast, no key required

Landing in later phases (each follows the open_meteo shape: async httpx +
`cached()` + graceful failure):
  Phase 1  amadeus (flight breadth), hotels (Hotelbeds/Expedia sandbox)
  Phase 2  camofox (browser research), youtube, reddit, gdelt, frankfurter (FX),
           halal (JAKIM/MUIS/HalalTrip/Zabihah cross-check with confidence label)

Rules that apply to every tool in this package:
  1. Official API first, permitted public pages second, never bypass access controls.
  2. API = source of truth for structure; crawl = discovery + verification.
  3. Cache aggressively (Redis TTL 6–24h) to protect free quotas.
  4. A failing tool degrades the result, it never breaks the run.
"""

from app.tools import atlas_skill, open_meteo

__all__ = ["atlas_skill", "open_meteo"]
