"""Amadeus Self-Service API tool — flight search + cheapest dates (spec §9).

Secondary flight data source complementing the Atlas Flight Booking Skill.
Used for broad search / price-calendar / cheapest-date queries in the test
environment.  The Atlas skill remains the primary booking path (search →
verify → book → pay → ticket).

Free tier (test env): limited inventory, 3,000 API calls/month.
Cache aggressively (6h) to protect quota.

Auth: OAuth2 client-credentials → bearer token (cached until expiry).
Docs: https://developers.amadeus.com/self-service/category/flights
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core import vault
from app.core.cache import cached
from app.core.settings import settings

logger = logging.getLogger(__name__)

# Test environment URLs (switch to production URLs when keys are live)
AUTH_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
SEARCH_URL = "https://test.api.amadeus.com/v2/shopping/flight-offers"
CHEAPEST_URL = "https://test.api.amadeus.com/v1/shopping/flight-destinations"
TIMEOUT = httpx.Timeout(20.0)

_token: str | None = None
_token_expiry: float = 0


async def _get_token() -> str | None:
    """Obtain or refresh the OAuth2 bearer token (cached in memory)."""
    global _token, _token_expiry  # noqa: PLW0603

    resolved = await vault.resolve("amadeus")
    api_secret = resolved.get("secret") if resolved else None
    api_key = (resolved.get("extra") or {}).get("client_id") if resolved else None
    api_key = api_key or getattr(settings, "amadeus_client_id", None)
    if not api_key or not api_secret:
        logger.debug("No Amadeus credential in the vault — skipping")
        return None

    if _token and time.time() < _token_expiry - 60:
        return _token

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                AUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": api_key,
                    "client_secret": api_secret,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            _token = body["access_token"]
            _token_expiry = time.time() + body.get("expires_in", 1799)
            return _token
    except Exception as exc:  # noqa: BLE001
        logger.warning("Amadeus auth failed: %s", exc)
        return None


async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    *,
    return_date: str | None = None,
    adults: int = 1,
    max_results: int = 10,
    currency: str = "MYR",
) -> list[dict[str, Any]] | None:
    """Search one-way or round-trip flight offers.

    Returns lightweight offer descriptors or ``None`` when credentials are
    missing / API fails.  Cached for 6 h.
    """
    token = await _get_token()
    if not token:
        return None

    params: dict[str, Any] = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": departure_date,
        "adults": adults,
        "max": max_results,
        "currencyCode": currency,
    }
    if return_date:
        params["returnDate"] = return_date

    cache_key = (
        f"amadeus:search:{origin}:{destination}:{departure_date}"
        f":{return_date or 'ow'}:{adults}:{max_results}"
    )

    async def fetch() -> list[dict[str, Any]] | None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                SEARCH_URL,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            offers = resp.json().get("data", [])
            results: list[dict[str, Any]] = []
            for offer in offers:
                segs = offer.get("itineraries", [{}])[0].get("segments", [])
                first = segs[0] if segs else {}
                last = segs[-1] if segs else {}
                results.append(
                    {
                        "offer_id": offer.get("id"),
                        "airline": first.get("carrierCode", ""),
                        "departure": first.get("departure", {}),
                        "arrival": last.get("arrival", {}),
                        "stops": len(segs) - 1,
                        "price_amount": float(offer.get("price", {}).get("total", 0)),
                        "price_currency": offer.get("price", {}).get("currency", currency),
                        "booking_class": first.get("cabin", "ECONOMY"),
                        "source": "amadeus",
                    }
                )
            return results

    try:
        return await cached(cache_key, fetch, ttl=settings.cache_ttl_short)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Amadeus search failed %s→%s: %s", origin, destination, exc)
    return None


async def cheapest_dates(
    origin: str,
    destination: str,
    *,
    departure_date: str | None = None,
    one_way: bool = True,
) -> list[dict[str, Any]] | None:
    """Find cheapest travel dates (Flight Destinations API).

    Useful for flexible travelers — "when is the cheapest time to fly
    KUL→VCE?"  Cached for 12 h.
    """
    token = await _get_token()
    if not token:
        return None

    params: dict[str, Any] = {
        "origin": origin,
        "destination": destination,
        "oneWay": str(one_way).lower(),
    }
    if departure_date:
        params["departureDate"] = departure_date

    async def fetch() -> list[dict[str, Any]] | None:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                CHEAPEST_URL,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            return [
                {
                    "destination": d.get("destination", ""),
                    "departure_date": d.get("departureDate", ""),
                    "return_date": d.get("returnDate"),
                    "price": float(d.get("price", {}).get("total", 0)),
                }
                for d in data
            ]

    cache_key = f"amadeus:cheapest:{origin}:{destination}:{departure_date or 'any'}"
    try:
        return await cached(cache_key, fetch, ttl=settings.cache_ttl_long)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Amadeus cheapest_dates failed: %s", exc)
    return None
