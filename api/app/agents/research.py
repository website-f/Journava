"""Research / Travel-Intelligence Agent (spec §4.4).

Camofox + YouTube/Reddit for sentiment, popularity and contradiction detection.
Also owns halal verification (§7.5): certified / muslim_friendly / unverified —
never claim "certified" without a certification source.

Phase 2: uses LLM to generate destination intelligence (attractions, dining,
safety, customs). Camofox + YouTube/Reddit arrive in Phase 3 as dedicated
browser research integrations.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts import research_messages
from app.agents.schemas import AgentResult, Option, Scope, TravelerProfile, TripRequest
from app.core.llm import LLMUnavailableError, complete

logger = logging.getLogger(__name__)


class ResearchAgent(BaseAgent):
    slug = "research"
    name = "Research"
    role = "Camofox · YouTube · Reddit"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        applied: dict[str, Scope] = {}

        if profile.halal_required:
            applied["halal_required"] = "hard_filter"
        if profile.allergies:
            applied["allergies"] = "hard_filter"
        if profile.interests:
            applied["interests"] = "soft_ranking"

        destination = request.destination or "unknown"
        self.emit("working", f"Generating destination intelligence for {destination}")

        # Attempt LLM-based research
        data = await self._generate_intelligence(request, profile)

        # Build option list from attractions + dining (for the Research Board tab)
        options = self._build_options(data, request.budget_currency)

        # Count items for summary
        n_attractions = len(data.get("attractions", []))
        n_dining = len(data.get("dining", []))
        summary = f"{n_attractions} attractions, {n_dining} dining picks for {destination}"
        if data.get("sentiment_summary"):
            summary += f" — {data['sentiment_summary']}"

        return AgentResult(
            agent=self.slug,
            summary=summary,
            options=options,
            applied_preferences=applied,
            warnings=(
                ["Halal results carry a confidence label — never an unverified claim"]
                if profile.halal_required
                else []
            ),
            data=data,
        )

    async def _generate_intelligence(
        self,
        request: TripRequest,
        profile: TravelerProfile,
    ) -> dict[str, Any]:
        """Call LLM for destination intelligence. Falls back to static data."""
        try:
            messages = research_messages(request, profile)
            raw_text = await complete(messages, response_format={"type": "json_object"})
            data = json.loads(raw_text)
            # Ensure required keys exist
            data.setdefault("attractions", [])
            data.setdefault("dining", [])
            data.setdefault("safety_tips", [])
            data.setdefault("customs", [])
            data.setdefault("best_times", [])
            data.setdefault("sentiment_summary", "")
            return data
        except (LLMUnavailableError, json.JSONDecodeError) as exc:
            logger.warning("Research LLM failed: %s", exc)
            self.emit("waiting", f"LLM unavailable: {type(exc).__name__}")
            return self._fallback_intelligence(request.destination)

    @staticmethod
    def _fallback_intelligence(destination: str | None) -> dict[str, Any]:
        """Static intelligence when LLM is unavailable."""
        dest = destination or "your destination"
        return {
            "attractions": [
                {"title": f"Central Market — {dest}", "kind": "market", "reasoning": "Iconic local experience (mock data)", "estimated_cost": 15.00, "cost_currency": "MYR"},
                {"title": f"Old Town Walking Tour — {dest}", "kind": "landmark", "reasoning": "Covers major historical sites (mock data)", "estimated_cost": 0, "cost_currency": "MYR"},
                {"title": f"National Museum — {dest}", "kind": "museum", "reasoning": "Best overview of local culture (mock data)", "estimated_cost": 10.00, "cost_currency": "MYR"},
            ],
            "dining": [
                {"title": f"Local Street Food Hub — {dest}", "cuisine": "Local", "halal_confidence": "muslim_friendly", "reasoning": "Popular with locals (mock data)", "estimated_cost": 20.00, "cost_currency": "MYR"},
                {"title": f"Riverside Restaurant — {dest}", "cuisine": "Fusion", "halal_confidence": "unverified", "reasoning": "Scenic dining (mock data)", "estimated_cost": 60.00, "cost_currency": "MYR"},
            ],
            "safety_tips": ["Keep valuables secure in crowded areas", "Use registered taxi services"],
            "customs": ["Remove shoes before entering temples/homes", "Tipping is appreciated but not mandatory"],
            "best_times": ["Early morning for popular attractions", "Evening for street food"],
            "sentiment_summary": f"{dest} is well-regarded by travelers for culture and food. Set DASHSCOPE_API_KEY for detailed AI intelligence.",
        }

    @staticmethod
    def _build_options(data: dict[str, Any], currency: str) -> list[Option]:
        """Convert attractions + dining into Option objects for the Research Board."""
        options: list[Option] = []

        for item in data.get("attractions", []):
            options.append(Option(
                id=f"RSH-A{len(options)+1:03d}",
                kind="activity",
                title=item.get("title", "Attraction"),
                price_amount=Decimal(str(item["estimated_cost"])) if item.get("estimated_cost") else None,
                price_currency=item.get("cost_currency", currency),
                reasoning=item.get("reasoning"),
                raw={"source": "research", "kind": item.get("kind", "attraction")},
            ))

        for item in data.get("dining", []):
            options.append(Option(
                id=f"RSH-D{len(options)+1:03d}",
                kind="restaurant",
                title=item.get("title", "Restaurant"),
                price_amount=Decimal(str(item["estimated_cost"])) if item.get("estimated_cost") else None,
                price_currency=item.get("cost_currency", currency),
                reasoning=item.get("reasoning"),
                halal_confidence=item.get("halal_confidence"),
                raw={"source": "research", "cuisine": item.get("cuisine", "")},
            ))

        return options
