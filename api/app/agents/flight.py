"""Flight Agent — wraps the Atlas Flight Booking Skill (spec §4.2).

Key rule (§7.5): flights always reference the **global** inventory. Dietary and
personal preferences never remove flight options — they only influence ranking
(timing, connections, budget) and add booking-time requests such as the halal
special meal code MOML.

Phase 1: attempts Atlas CLI → on failure calls LLM for realistic mock options →
ranks into 4 buckets → caches via Redis.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts import flight_messages
from app.agents.schemas import AgentResult, Option, Scope, TravelerProfile, TripRequest
from app.core.cache import cached
from app.core.llm import LLMUnavailableError, complete
from app.core.settings import settings
from app.tools.atlas_skill import AtlasSkillError, search as atlas_search

logger = logging.getLogger(__name__)


class FlightAgent(BaseAgent):
    slug = "flight"
    name = "Flight"
    role = "Atlas skill · search → verify → book → pay → ticket"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        # Inventory stays global — we only record how prefs affect ranking.
        applied: dict[str, Scope] = {}
        special_requests: dict[str, str] = {}

        if profile.halal_required:
            # Never a filter on flights; becomes a meal request at booking time.
            applied["halal_required"] = "not_applicable"
            special_requests["meal_code"] = "MOML"
        if profile.avoid_red_eye:
            applied["avoid_red_eye"] = "soft_ranking"
        if profile.max_connections is not None:
            applied["max_connections"] = "soft_ranking"
        if request.budget_amount is not None:
            applied["budget"] = "soft_ranking"

        origin = request.origin or profile.home_airport or "KUL"
        destination = request.destination or "unknown"
        depart = str(request.start_date) if request.start_date else "flexible"

        self.emit("working", f"Searching flights {origin} → {destination}")

        # --- Try Atlas CLI first, then LLM fallback ---
        options = await self._search(request, profile, origin, destination, depart)

        # --- Verification pass (spec §5 reconciliation pattern) ---
        options = self._verify(options)

        # --- Build ranking buckets ---
        ranking = self._rank(options)

        return AgentResult(
            agent=self.slug,
            summary=f"{len(options)} flight options found ({origin} → {destination})",
            options=options,
            applied_preferences=applied,
            data={"special_requests": special_requests, "scope": "global", "ranking": ranking},
        )

    async def _search(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        origin: str,
        destination: str,
        depart: str,
    ) -> list[Option]:
        """Attempt Atlas CLI, fall back to LLM generation, cache either way."""

        cache_key = f"flight:{origin}:{destination}:{depart}:{request.travellers}"

        async def producer() -> list[dict[str, Any]]:
            # 1. Try Atlas CLI
            try:
                self.emit("working", "Calling Atlas Flight Booking Skill (sandbox)")
                raw = await atlas_search(
                    origin,
                    destination,
                    depart,
                    return_date=str(request.end_date) if request.end_date else None,
                    adults=request.travellers,
                )
                return self._parse_atlas(raw)
            except AtlasSkillError as exc:
                logger.info("Atlas unavailable (%s), falling back to LLM", exc)
                self.emit("working", "Atlas unavailable — generating options via LLM")

            # 2. LLM fallback
            try:
                messages = flight_messages(request, profile)
                raw_text = await complete(messages, response_format={"type": "json_object"})
                data = json.loads(raw_text)
                return data.get("options", [])
            except (LLMUnavailableError, json.JSONDecodeError) as exc:
                logger.warning("Flight LLM failed: %s", exc)
                self.emit("waiting", f"LLM unavailable: {type(exc).__name__}")
                return self._mock_options(origin, destination, depart)

        raw_options = await cached(cache_key, producer, ttl=settings.cache_ttl_short)

        # Parse into Option models
        options: list[Option] = []
        for opt in raw_options or []:
            try:
                options.append(Option(
                    id=opt.get("id", f"FL{len(options)+1:03d}"),
                    kind="flight",
                    title=opt.get("title", "Flight"),
                    price_amount=Decimal(str(opt["price_amount"])) if opt.get("price_amount") else None,
                    price_currency=opt.get("price_currency", request.budget_currency),
                    provider=opt.get("provider"),
                    reasoning=opt.get("reasoning"),
                    verified=opt.get("verified", False),
                    last_checked=opt.get("last_checked"),
                    raw=opt.get("raw", {}),
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping malformed flight option: %s", exc)
        return options

    @staticmethod
    def _parse_atlas(raw: dict[str, Any]) -> list[dict[str, Any]]:
        """Transform Atlas CLI JSON into our Option shape."""
        offers = raw.get("offers") or raw.get("results") or []
        options: list[dict[str, Any]] = []
        for i, offer in enumerate(offers[:5]):
            options.append({
                "id": offer.get("id", f"ATLAS{i+1:03d}"),
                "title": f"{offer.get('airline', 'Unknown')} — {offer.get('flight_number', '')}",
                "price_amount": offer.get("price", {}).get("total"),
                "price_currency": offer.get("price", {}).get("currency", "MYR"),
                "provider": "Atlas Flight Booking Skill",
                "reasoning": f"Direct from Atlas (verified, sandbox mode)",
                "verified": True,
                "last_checked": "just now",
                "raw": offer,
            })
        return options

    @staticmethod
    def _verify(options: list[Option]) -> list[Option]:
        """Price consistency check (spec §5). Marks options verified/outlier."""
        prices = [float(o.price_amount) for o in options if o.price_amount is not None]
        if len(prices) < 2:
            return options

        prices.sort()
        median = prices[len(prices) // 2]
        now = "just now"

        for opt in options:
            if opt.price_amount is None:
                continue
            price = float(opt.price_amount)
            deviation = abs(price - median) / median if median > 0 else 0
            if deviation <= 0.20:
                opt.verified = True
                opt.last_checked = now
            else:
                opt.verified = False
                opt.last_checked = now
                if opt.reasoning:
                    opt.reasoning += " (price outlier — verify before booking)"
                else:
                    opt.reasoning = "Price outlier — verify before booking"
        return options

    @staticmethod
    def _rank(options: list[Option]) -> dict[str, str | None]:
        """Build 4-bucket ranking from options."""
        priced = [(o, float(o.price_amount or 0)) for o in options if o.price_amount]
        if not priced:
            return {"cheapest": None, "cheapest_with_baggage": None, "best_value": None, "best_time": None}

        priced.sort(key=lambda x: x[1])
        cheapest = priced[0][0].id

        # Cheapest with baggage
        with_baggage = next(
            (o for o, _ in priced if o.raw.get("baggage_included")),
            priced[0][0],
        )

        # Best value (lowest price among 0-stop flights, or just second-cheapest)
        direct = [(o, p) for o, p in priced if o.raw.get("stops", 1) == 0]
        best_value = direct[0][0].id if direct else (priced[1][0].id if len(priced) > 1 else priced[0][0].id)

        # Best time (shortest duration)
        by_duration = sorted(priced, key=lambda x: x[0].raw.get("duration_hours", 99))
        best_time = by_duration[0][0].id

        return {
            "cheapest": cheapest,
            "cheapest_with_baggage": with_baggage.id,
            "best_value": best_value,
            "best_time": best_time,
        }

    @staticmethod
    def _mock_options(origin: str, destination: str, depart: str) -> list[dict[str, Any]]:
        """Structured mock when both Atlas and LLM are unavailable."""
        return [
            {
                "id": "FL001",
                "title": f"Mock Direct — {origin} to {destination}",
                "price_amount": 850.00,
                "price_currency": "MYR",
                "provider": "Mock (no LLM key)",
                "reasoning": "Cheapest direct option (mock data — set DASHSCOPE_API_KEY for real results)",
                "verified": False,
                "raw": {"bucket": "cheapest", "stops": 0, "departure_time": "08:00", "duration_hours": 4.5},
            },
            {
                "id": "FL002",
                "title": f"Mock Value — {origin} to {destination}",
                "price_amount": 1200.00,
                "price_currency": "MYR",
                "provider": "Mock (no LLM key)",
                "reasoning": "Best value with included baggage (mock data)",
                "verified": False,
                "raw": {"bucket": "best_value", "stops": 0, "departure_time": "14:30", "duration_hours": 4.5, "baggage_included": True},
            },
            {
                "id": "FL003",
                "title": f"Mock Budget — {origin} to {destination} (1 stop)",
                "price_amount": 620.00,
                "price_currency": "MYR",
                "provider": "Mock (no LLM key)",
                "reasoning": "Cheapest overall with 1 stop (mock data)",
                "verified": False,
                "raw": {"bucket": "cheapest", "stops": 1, "departure_time": "06:15", "duration_hours": 7.0},
            },
        ]
