"""Concierge Agent — restaurant reservations, event bookings, special requests.

Research-backed: crawls Camofox for what's actually bookable/on at the
destination and cites its sources.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, Option, TravelerProfile, TripRequest
from app.core import llm
from app.tools import discover

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Concierge agent. Suggest bookable experiences, \
grounded in the RESEARCH provided (real, named, currently-open places/events).
Respond in JSON:
{"reservations": [{"name": "restaurant", "cuisine": "type", "reserve_by": "phone|website", "avg_cost_usd": 30}],
 "events": [{"name": "event", "date": "date", "book_via": "website"}],
 "special_services": ["spa", "private tour"]}"""

USER = (
    "Destination: {destination}\nInterests: {interests}\n\n"
    "RESEARCH (live web crawl):\n{research}\n\n"
    "Suggest bookable experiences, favouring specific named places from the research."
)


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

        self.emit("working", f"Researching what's bookable in {destination}")
        research = await discover.crawl_sources(
            [
                f"{destination} best restaurants to book reservations {interests}",
                f"{destination} events things to book this month",
            ]
        )

        try:
            resp = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": USER.format(
                            destination=destination,
                            interests=interests,
                            research=research["text"] or "(no live results — use best knowledge)",
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="concierge",
            )
            data = json.loads(resp)
            if not isinstance(data, dict):
                raise TypeError("LLM did not return a JSON object")
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
            if isinstance(r, dict)
        ]
        sources = discover.source_links(research["sources"])
        return AgentResult(
            agent=self.slug,
            summary=f"Concierge picks for {destination}",
            options=options,
            data={"destination": destination, **data, "sources": sources},
        )
