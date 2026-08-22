"""Itinerary Agent — day-by-day plan assembly (spec §4.7).

Phase 1: receives upstream results (flights, hotels, research, weather) through
the context dict and calls LLM to assemble a coherent day-by-day itinerary.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts import itinerary_messages
from app.agents.schemas import AgentResult, ItineraryItem, Scope, TravelerProfile, TripRequest
from app.core.llm import LLMUnavailableError, complete

logger = logging.getLogger(__name__)

#: Rough activity budget per day, driven by the traveller's pace preference.
ITEMS_PER_DAY = {"relaxed": 2, "balanced": 3, "packed": 5}


class ItineraryAgent(BaseAgent):
    slug = "itinerary"
    name = "Itinerary"
    role = "Day-by-day assembly"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        pace = request.pace or profile.pace
        applied: dict[str, Scope] = {"pace": "soft_ranking"}

        upstream = context or {}
        self.emit("working", f"Assembling itinerary (pace: {pace})")

        items = await self._assemble(request, profile, upstream, pace)

        return AgentResult(
            agent=self.slug,
            summary=f"Itinerary assembled: {len(items)} items across the trip",
            items=items,
            applied_preferences=applied,
            data={
                "pace": pace,
                "target_items_per_day": ITEMS_PER_DAY.get(pace, 3),
                "total_items": len(items),
            },
        )

    async def _assemble(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        upstream: dict[str, Any],
        pace: str,
    ) -> list[ItineraryItem]:
        """Call LLM to produce day-by-day items, with a mock fallback."""
        try:
            messages = itinerary_messages(request, profile, upstream)
            raw_text = await complete(messages, response_format={"type": "json_object"})
            data = json.loads(raw_text)
            raw_items = data.get("items", [])
        except (LLMUnavailableError, json.JSONDecodeError) as exc:
            logger.warning("Itinerary LLM failed: %s", exc)
            self.emit("waiting", f"LLM unavailable: {type(exc).__name__}")
            raw_items = self._mock_items(request, pace)

        # Hard guarantee: never return more days than the trip is long, even if
        # the LLM ignores the instruction ("3 days" must not yield a 7-day plan).
        max_day = request.effective_days
        items: list[ItineraryItem] = []
        for item in raw_items:
            if int(item.get("day_index", 1) or 1) > max_day:
                continue
            try:
                items.append(
                    ItineraryItem(
                        day_index=item.get("day_index", 1),
                        kind=item.get("kind", "activity"),
                        title=item.get("title", "Activity"),
                        starts_at=item.get("starts_at"),
                        ends_at=item.get("ends_at"),
                        reasoning=item.get("reasoning"),
                        cost_amount=Decimal(str(item["cost_amount"]))
                        if item.get("cost_amount")
                        else None,
                        cost_currency=item.get("cost_currency", request.budget_currency),
                        details=item.get("details", {}),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skipping malformed itinerary item: %s", exc)
        return items

    @staticmethod
    def _mock_items(request: TripRequest, pace: str) -> list[dict[str, Any]]:
        """Structured mock itinerary when LLM is unavailable."""
        days = request.effective_days

        destination = request.destination or "the destination"
        items_per_day = ITEMS_PER_DAY.get(pace, 3)

        items: list[dict[str, Any]] = []
        for day in range(1, days + 1):
            items.append(
                {
                    "day_index": day,
                    "kind": "activity",
                    "title": f"Day {day}: Explore {destination} (mock data)",
                    "starts_at": "09:00",
                    "ends_at": "12:00",
                    "reasoning": f"Mock itinerary — set DASHSCOPE_API_KEY for real AI-generated plan (pace: {pace}, target {items_per_day}/day)",
                    "cost_amount": 50.0,
                    "cost_currency": request.budget_currency,
                }
            )
            items.append(
                {
                    "day_index": day,
                    "kind": "meal",
                    "title": f"Day {day}: Lunch at local restaurant",
                    "starts_at": "12:30",
                    "ends_at": "13:30",
                    "reasoning": "Midday break for local cuisine",
                    "cost_amount": 30.0,
                    "cost_currency": request.budget_currency,
                }
            )
        return items
