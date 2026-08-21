"""Sustainability Agent — carbon footprint estimate, eco-friendly options.

Research-backed: crawls Camofox for real eco options at the destination and cites
its sources, rather than answering from the model's memory alone.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm
from app.tools import discover

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Sustainability agent. Estimate trip environmental \
impact and suggest eco options, grounded in the RESEARCH provided.
Respond in JSON:
{"flight_co2_kg": 500, "eco_tips": ["tip1", "tip2"], "green_hotels": ["named eco hotel"],
 "carbon_offset_usd": 15, "sustainability_score": "low|medium|high"}
Prefer specific, named eco-certified places from the research over generic advice."""

USER = (
    "Destination: {destination}\nOrigin: {origin}\nDays: {days}\n\n"
    "RESEARCH (live web crawl):\n{research}\n\n"
    "Estimate environmental impact and suggest concrete eco options."
)


class SustainabilityAgent(BaseAgent):
    slug = "sustainability"
    name = "Sustainability"
    role = "Carbon estimate · eco options · offsets"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"
        origin = request.origin or "Kuala Lumpur"
        days = (
            (request.end_date - request.start_date).days
            if request.start_date and request.end_date
            else 7
        )

        self.emit("working", f"Researching eco options in {destination}")
        research = await discover.crawl_sources(
            [
                f"sustainable eco friendly travel {destination} green hotels",
                f"{destination} carbon offset public transport eco tips",
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
                            origin=origin,
                            days=days,
                            research=research["text"] or "(no live results — use best knowledge)",
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="sustainability",
            )
            data = json.loads(resp)
            if not isinstance(data, dict):
                raise TypeError("LLM did not return a JSON object")
        except Exception:  # noqa: BLE001
            data = {
                "flight_co2_kg": 0,
                "eco_tips": ["Choose direct flights", "Use public transit"],
                "carbon_offset_usd": 10,
                "sustainability_score": "medium",
            }

        sources = discover.source_links(research["sources"])
        return AgentResult(
            agent=self.slug,
            summary=f"Carbon: ~{data.get('flight_co2_kg', '?')}kg CO2 — offset ~${data.get('carbon_offset_usd', '?')}",
            data={"destination": destination, **data, "sources": sources},
        )
