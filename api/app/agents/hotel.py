"""Hotel Agent — sandbox APIs + research; compare and auto-switch (spec §4.3).

Phase 1: calls LLM to generate realistic hotel options, applies preference
scoping, caches results via Redis.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts import hotel_messages
from app.agents.schemas import AgentResult, Option, Scope, TravelerProfile, TripRequest
from app.core.cache import cached
from app.core.llm import LLMUnavailableError, complete
from app.core.settings import settings

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

        # Build ranking buckets (spec §5 reconciliation pattern)
        ranking = self._rank(options)

        return AgentResult(
            agent=self.slug,
            summary=f"{len(options)} hotel options found in {destination}",
            options=options,
            applied_preferences=applied,
            data={"ranking": ranking},
        )

    async def _search(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        destination: str,
    ) -> list[Option]:
        """LLM-generate hotel options, cache via Redis."""

        cache_key = (
            f"hotel:{destination}:{request.start_date}:{request.end_date}:{request.travellers}"
        )

        async def producer() -> list[dict[str, Any]]:
            try:
                messages = hotel_messages(request, profile)
                raw_text = await complete(messages, response_format={"type": "json_object"})
                data = json.loads(raw_text)
                return data.get("options", [])
            except (LLMUnavailableError, json.JSONDecodeError) as exc:
                logger.warning("Hotel LLM failed: %s", exc)
                self.emit("waiting", f"LLM unavailable: {type(exc).__name__}")
                return self._mock_options(destination)

        raw_options = await cached(cache_key, producer, ttl=settings.cache_ttl_short)

        options: list[Option] = []
        for opt in raw_options or []:
            try:
                options.append(
                    Option(
                        id=opt.get("id", f"HT{len(options) + 1:03d}"),
                        kind="hotel",
                        title=opt.get("title", "Hotel"),
                        price_amount=Decimal(str(opt["price_amount"]))
                        if opt.get("price_amount")
                        else None,
                        price_currency=opt.get("price_currency", request.budget_currency),
                        provider=opt.get("provider"),
                        reasoning=opt.get("reasoning"),
                        verified=opt.get("verified", False),
                        last_checked=opt.get("last_checked"),
                        raw=opt.get("raw", {}),
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

        priced.sort(key=lambda x: x[1])
        cheapest = priced[0][0].id

        # Best location (near transit)
        near_transit = next(
            (o for o, _ in priced if o.raw.get("near_transit")),
            priced[0][0],
        )

        # Best value (mid-range with good amenities)
        mid_range = [x for x in priced if x[1] > priced[0][1]]
        best_value = mid_range[0][0].id if mid_range else priced[0][0].id

        # Highest rated (most stars)
        by_stars = sorted(priced, key=lambda x: x[0].raw.get("stars", 0), reverse=True)
        highest_rated = by_stars[0][0].id

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
