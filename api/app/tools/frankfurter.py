"""Frankfurter FX rates tool — no API key, generous limits (spec §9).

Follows the Open-Meteo pattern: async httpx, hard caching through Redis,
graceful failure. FX rates change slowly so a 24h TTL is safe.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger(__name__)

RATES_URL = "https://api.frankfurter.dev/v1/latest"
TIMEOUT = httpx.Timeout(15.0)


async def rates(base: str = "MYR") -> dict[str, float] | None:
    """Return currency->rate mapping with *base* as the reference.

    Cached for 24h. Returns None on any failure so callers can degrade gracefully.
    """

    async def fetch() -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(RATES_URL, params={"base": base})
            response.raise_for_status()
            data = response.json()
            return data.get("rates")

    try:
        return await cached(
            f"frankfurter:rates:{base.upper()}",
            fetch,
            ttl=settings.cache_ttl_long,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Frankfurter FX failed for base %s: %s", base, exc)
        return None


async def convert(amount: float, from_currency: str, to_currency: str) -> float | None:
    """Convert a single amount between two currencies. Returns None on failure."""
    fx = await rates(from_currency)
    if fx is None:
        return None
    rate = fx.get(to_currency.upper())
    if rate is None:
        return None
    return round(amount * rate, 2)
