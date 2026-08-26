"""Hotel Agent — sandbox APIs + research; compare and auto-switch (spec §4.3).

Phase 1: calls LLM to generate realistic hotel options, applies preference
scoping, caches results via Redis.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any
from urllib.parse import quote_plus

from app.agents.base import BaseAgent
from app.agents.prompts import hotel_messages
from app.agents.schemas import AgentResult, Option, Scope, TravelerProfile, TripRequest
from app.core.cache import cached
from app.core.llm import LLMUnavailableError, complete
from app.core.settings import settings
from app.supplier import store as supplier_store


def _hotel_link(title: str, destination: str) -> str:
    """The primary 'View & book' target — a Booking.com search for the property.
    Booking.com's search reliably resolves the property (Google Hotels' deep link
    often lands on an empty result), and the full OTA set is in `ota_links`."""
    return "https://www.booking.com/searchresults.html?ss=" + quote_plus(f"{title} {destination}")


def _ota_links(title: str, destination: str) -> list[dict[str, str]]:
    """Compare-and-book links across the major OTAs for one property, so the
    traveller isn't stuck with a single Google link. Deterministic search URLs
    (no key needed) — the same property on Booking.com, Agoda, Trip.com, etc."""
    q = quote_plus(f"{title} {destination}")
    return [
        {"name": "Booking.com", "url": f"https://www.booking.com/searchresults.html?ss={q}"},
        {"name": "Agoda", "url": f"https://www.agoda.com/search?q={q}"},
        {"name": "Trip.com", "url": f"https://www.trip.com/hotels/list?searchValue={q}"},
        {"name": "Hotels.com", "url": f"https://www.hotels.com/Hotel-Search?q-destination={q}"},
        {"name": "Google", "url": f"https://www.google.com/travel/search?q={q}"},
    ]

logger = logging.getLogger(__name__)


class HotelAgent(BaseAgent):
    slug = "hotel"
    name = "Hotel"
    role = "Compare & auto-switch"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        applied: dict[str, Scope] = {}

        if profile.halal_required:
            # Hotels are a soft signal only (halal breakfast option), never a filter.
            applied["halal_required"] = "soft_ranking"
        if profile.accessibility:
            # Accessibility is a hard filter for hotels (§7.5 matrix).
            applied["accessibility"] = "hard_filter"
        if request.budget_amount is not None:
            applied["budget"] = "soft_ranking"

        destination = request.destination or "unknown"
        self.emit("working", f"Searching hotels in {destination}")

        options = await self._search(request, profile, destination)

        # Partner (direct) inventory ranks alongside the crawled/LLM options but
        # is bookable and keeps the guest relationship with the property — the
        # B2B side of the marketplace (no OTA commission).
        direct = await self._supplier_options(destination)
        options = direct + options

        # Rank the list itself by real value (price vs stars/amenities/transit),
        # honouring the halal soft-boost and accessibility hard-preference the
        # scope declared — previously declared but never implemented.
        options, warnings = self._apply_ranking(options, profile)
        ranking = self._rank(options)

        direct_note = f" · {len(direct)} direct from partners" if direct else ""
        return AgentResult(
            agent=self.slug,
            summary=f"{len(options)} hotel options found in {destination}{direct_note}",
            options=options,
            applied_preferences=applied,
            warnings=warnings,
            data={"ranking": ranking, "direct_count": len(direct)},
        )

    @staticmethod
    def _apply_ranking(
        options: list[Option], profile: TravelerProfile
    ) -> tuple[list[Option], list[str]]:
        """Sort by value = cheaper price + more stars/amenities/transit, with a
        halal boost and accessibility ordering. Never removes an option."""
        priced = [float(o.price_amount) for o in options if o.price_amount is not None]
        p_lo, p_hi = (min(priced), max(priced)) if priced else (0.0, 1.0)
        warnings: list[str] = []

        def norm(v: float) -> float:
            return 0.0 if p_hi <= p_lo else max(0.0, min(1.0, (v - p_lo) / (p_hi - p_lo)))

        def is_halal(o: Option) -> bool:
            raw = o.raw or {}
            ams = " ".join(str(a).lower() for a in (raw.get("amenities") or []))
            return bool(raw.get("halal_friendly")) or "halal" in ams

        def is_accessible(o: Option) -> bool:
            return bool((o.raw or {}).get("accessibility"))

        def score(o: Option) -> float:
            raw = o.raw or {}
            price = float(o.price_amount) if o.price_amount is not None else p_hi
            stars = float(raw.get("stars") or 0)
            amenities = raw.get("amenities") or []
            quality = stars / 5.0 + min(len(amenities), 6) * 0.04
            if raw.get("near_transit"):
                quality += 0.10
            if o.bookable:
                quality += 0.06
            if profile.halal_required and is_halal(o):
                quality += 0.20
            s = norm(price) - 0.6 * quality  # lower = better value
            if profile.accessibility and not is_accessible(o):
                s += 5.0  # accessibility is a hard preference — push non-accessible down
            return s

        ranked = sorted(options, key=score)
        if profile.accessibility:
            accessible = [o for o in ranked if is_accessible(o)]
            if not accessible:
                warnings.append(
                    "No listings confirmed step-free — showing all; verify accessibility with the property."
                )
            elif len(accessible) < len(ranked):
                warnings.append("Accessible rooms ranked first; some listings below may not be step-free.")
        return ranked, warnings

    async def _supplier_options(self, destination: str) -> list[Option]:
        """Bookable direct listings from partner suppliers for this destination."""
        try:
            listings = await supplier_store.search_for_destination(destination)
        except Exception as exc:  # noqa: BLE001 — a partner miss never breaks a run
            logger.debug("supplier search failed: %s", exc)
            return []

        options: list[Option] = []
        for item in listings:
            price = item.get("price_amount")
            options.append(
                Option(
                    id=f"SUP-{item['listing_id'][:8]}",
                    kind="hotel",
                    title=f"{item['property_name']} — {item['title']}",
                    price_amount=Decimal(str(price)) if price is not None else None,
                    price_currency=item.get("price_currency", "MYR"),
                    provider=f"Direct · {item['property_name']}",
                    reasoning=(
                        "Direct from the property — no OTA commission; booking connects "
                        "you straight to the hotel."
                    ),
                    verified=True,
                    source="supplier",
                    bookable=True,
                    raw={
                        "source": "supplier",
                        "direct": True,
                        "listing_id": item["listing_id"],
                        "property_id": item["property_id"],
                        "org_id": item["org_id"],
                        "halal_friendly": item.get("halal_friendly"),
                        "perks": item.get("perks", []),
                        "near_transit": False,
                        "stars": item.get("star_rating") or 0,
                        # Booking.com-style richness so the traveller sees the real
                        # direct listing (image, discount, description, amenities).
                        "image_url": item.get("image_url"),
                        "description": item.get("description"),
                        "original_price": item.get("original_price"),
                        "discount_pct": item.get("discount_pct"),
                        "amenities": item.get("amenities", []),
                        "rating": (item.get("star_rating") or 0) or None,
                    },
                )
            )
        if options:
            self.emit("active", f"{len(options)} direct listing(s) from partner properties")
        return options

    async def _search(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        destination: str,
    ) -> list[Option]:
        """LLM-generate hotel options, cache via Redis."""

        cache_key = (
            f"hotel:v2:{destination}:{request.start_date}:{request.end_date}:{request.travellers}"
        )

        async def producer() -> dict[str, Any]:
            from app.tools import discover

            # Ground the agent in a live crawl of booking sites — real names,
            # areas and nightly prices instead of invented ones.
            research = ""
            try:
                self.emit("working", f"Crawling live hotel rates in {destination}")
                res = await discover.crawl_sources(
                    [
                        f"best hotels in {destination} price per night",
                        f"{destination} hotels booking {request.travellers} guests near city centre",
                    ]
                )
                research = (res or {}).get("text", "")[:3500]
            except Exception as exc:  # noqa: BLE001 — a missing crawl never breaks the agent
                logger.info("hotel research crawl skipped: %s", exc)
            try:
                messages = hotel_messages(request, profile, research=research)
                raw_text = await complete(messages, response_format={"type": "json_object"})
                data = json.loads(raw_text)
                return {"options": data.get("options", []), "sourced": bool(research)}
            except (LLMUnavailableError, json.JSONDecodeError) as exc:
                logger.warning("Hotel LLM failed: %s", exc)
                self.emit("waiting", f"LLM unavailable: {type(exc).__name__}")
                return {"options": self._mock_options(destination), "sourced": False}

        payload = await cached(cache_key, producer, ttl=settings.cache_ttl_short)
        # Backward-compatible with any old list-shaped cache entries.
        raw_options = payload.get("options", []) if isinstance(payload, dict) else (payload or [])
        sourced = payload.get("sourced", False) if isinstance(payload, dict) else False

        options: list[Option] = []
        for opt in raw_options or []:
            try:
                title = opt.get("title", "Hotel")
                url = opt.get("booking_url") or opt.get("url")
                # Google Hotels deep links frequently land on an empty result —
                # prefer a Booking.com search that reliably resolves the property.
                if url and "google.com/travel" in url:
                    url = None
                link = url or _hotel_link(title, destination)
                # Grounded in the live crawl → tag it as researched, not invented.
                src = "camofox" if (sourced or url) else "llm"
                options.append(
                    Option(
                        id=opt.get("id", f"HT{len(options) + 1:03d}"),
                        kind="hotel",
                        title=title,
                        price_amount=Decimal(str(opt["price_amount"]))
                        if opt.get("price_amount")
                        else None,
                        price_currency=opt.get("price_currency", request.budget_currency),
                        provider=opt.get("provider"),
                        reasoning=opt.get("reasoning"),
                        verified=opt.get("verified", False),
                        last_checked=opt.get("last_checked"),
                        source=src,
                        source_url=link,
                        booking_url=link,
                        raw={
                            **(opt.get("raw") or {}),
                            "price_range": opt.get("price_range"),
                            # Prefer a top-level rating, else the one the prompt now
                            # nests in raw, else fall back to the star count so the
                            # card always shows a rating.
                            "rating": opt.get("rating")
                            or (opt.get("raw") or {}).get("rating")
                            or (opt.get("raw") or {}).get("stars"),
                            # A short guest-review snippet always shown on the card;
                            # falls back to the agent's reasoning when the model
                            # didn't emit a dedicated review.
                            "review": opt.get("review")
                            or (opt.get("raw") or {}).get("review")
                            or opt.get("reasoning"),
                            # Compare-and-book across the major OTAs (not just Google).
                            "ota_links": _ota_links(title, destination),
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping malformed hotel option: %s", exc)
        return options

    @staticmethod
    def _rank(options: list[Option]) -> dict[str, str | None]:
        """Build 4-bucket hotel ranking."""
        priced = [(o, float(o.price_amount or 0)) for o in options if o.price_amount]
        if not priced:
            return {
                "cheapest": None,
                "best_location": None,
                "best_value": None,
                "highest_rated": None,
            }

        cheapest = min(priced, key=lambda x: x[1])[0].id

        # Best location: near transit/central, else the top-value option.
        near_transit = next(
            (o for o in options if (o.raw or {}).get("near_transit")),
            options[0],
        )

        # Best value = the top of the value ranking (`options` arrives sorted by
        # _apply_ranking: price vs stars/amenities/transit/halal), not merely the
        # second-cheapest hotel.
        best_value = options[0].id

        # Highest rated (most stars).
        highest_rated = max(options, key=lambda o: float((o.raw or {}).get("stars") or 0)).id

        return {
            "cheapest": cheapest,
            "best_location": near_transit.id,
            "best_value": best_value,
            "highest_rated": highest_rated,
        }

    @staticmethod
    def _mock_options(destination: str) -> list[dict[str, Any]]:
        """Structured mock when LLM is unavailable."""
        return [
            {
                "id": "HT001",
                "title": f"Grand Heritage Hotel — {destination}",
                "price_amount": 380.00,
                "price_currency": "MYR",
                "provider": "Mock (no LLM key)",
                "reasoning": "Best value 4-star near city center (mock data — set DASHSCOPE_API_KEY for real results)",
                "raw": {
                    "stars": 4,
                    "location": "city center",
                    "amenities": ["wifi", "pool", "halal_breakfast"],
                    "near_transit": True,
                },
            },
            {
                "id": "HT002",
                "title": f"Boutique Suites — {destination}",
                "price_amount": 550.00,
                "price_currency": "MYR",
                "provider": "Mock (no LLM key)",
                "reasoning": "Premium boutique with rooftop, walking distance to attractions (mock data)",
                "raw": {
                    "stars": 5,
                    "location": "old town",
                    "amenities": ["wifi", "spa", "restaurant"],
                    "near_transit": True,
                },
            },
            {
                "id": "HT003",
                "title": f"Budget Inn — {destination}",
                "price_amount": 150.00,
                "price_currency": "MYR",
                "provider": "Mock (no LLM key)",
                "reasoning": "Most affordable option, clean and functional (mock data)",
                "raw": {
                    "stars": 3,
                    "location": "suburb",
                    "amenities": ["wifi"],
                    "near_transit": False,
                },
            },
        ]
