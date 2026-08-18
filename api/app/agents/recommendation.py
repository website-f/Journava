"""Recommendation Agent — personalized activity recommendations based on traveler profile."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, Option, TravelerProfile, TripRequest
from app.core import llm

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Recommendation engine. Suggest personalized activities.
Respond in JSON:
{"activities": [{"name": "activity", "why": "reason", "duration_hr": 2, "cost_usd": 20, "halal_confidence": null}]}"""

USER = "Destination: {destination}\nTraveler interests: {interests}\nPace: {pace}\nHalal required: {halal}\nSuggest 5 activities."


class RecommendationAgent(BaseAgent):
    slug = "recommendation"
    name = "Recommendation"
    role = "Personalized picks · based on profile"

    async def run(self, request: TripRequest, profile: TravelerProfile, *, context: dict[str, Any] | None = None) -> AgentResult:
        destination = request.destination or "unknown"
        interests = ", ".join(profile.interests) if profile.interests else "culture, food"

        try:
            resp = await llm.complete(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER.format(
                    destination=destination, interests=interests, pace=profile.pace, halal=profile.halal_required)}],
                response_format={"type": "json_object"}, agent="recommendation",
            )
            data = json.loads(resp)
        except Exception:  # noqa: BLE001
            data = {"activities": []}

        options = [
            Option(id=f"rec-{i}", kind="activity", title=a.get("name", ""),
                   reasoning=a.get("why", ""), halal_confidence=a.get("halal_confidence"))
            for i, a in enumerate(data.get("activities", []))
        ]
        return AgentResult(agent=self.slug, summary=f"{len(options)} personalized picks for {destination}", options=options, data={"destination": destination, "activities": data.get("activities", [])})
