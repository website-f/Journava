"""Concierge Agent — restaurant reservations, event bookings, special requests."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, Option, TravelerProfile, TripRequest
from app.core import llm

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Concierge agent. Suggest bookable experiences.
Respond in JSON:
{"reservations": [{"name": "restaurant", "cuisine": "type", "reserve_by": "phone|website", "avg_cost_usd": 30}],
 "events": [{"name": "event", "date": "date", "book_via": "website"}],
 "special_services": ["spa", "private tour"]}"""

USER = "Destination: {destination}\nInterests: {interests}\nSuggest bookable experiences."


class ConciergeAgent(BaseAgent):
    slug = "concierge"
    name = "Concierge"
    role = "Reservations · events · special requests"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"
        interests = ", ".join(profile.interests) if profile.interests else "general sightseeing"

        try:
            resp = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": USER.format(destination=destination, interests=interests),
                    },
                ],
                response_format={"type": "json_object"},
                agent="concierge",
            )
            data = json.loads(resp)
        except Exception:  # noqa: BLE001
            data = {
                "reservations": [],
                "events": [],
                "special_services": ["Hotel concierge can assist"],
            }

        options = [
            Option(
                id=f"concierge-{i}",
                kind="restaurant",
                title=r.get("name", ""),
                reasoning=r.get("cuisine", ""),
            )
            for i, r in enumerate(data.get("reservations", []))
        ]
        return AgentResult(
            agent=self.slug,
            summary=f"Concierge picks for {destination}",
            options=options,
            data={"destination": destination, **data},
        )
