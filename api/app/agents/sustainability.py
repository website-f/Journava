"""Sustainability Agent — carbon footprint estimate, eco-friendly options."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Sustainability agent. Estimate trip environmental impact.
Respond in JSON:
{"flight_co2_kg": 500, "eco_tips": ["tip1", "tip2"], "green_hotels": ["hotel suggestion"],
 "carbon_offset_usd": 15, "sustainability_score": "low|medium|high"}"""

USER = "Destination: {destination}\nOrigin: {origin}\nDays: {days}\nEstimate environmental impact and suggest eco options."


class SustainabilityAgent(BaseAgent):
    slug = "sustainability"
    name = "Sustainability"
    role = "Carbon estimate · eco options · offsets"

    async def run(self, request: TripRequest, profile: TravelerProfile, *, context: dict[str, Any] | None = None) -> AgentResult:
        destination = request.destination or "unknown"
        origin = request.origin or "Kuala Lumpur"
        days = (request.end_date - request.start_date).days if request.start_date and request.end_date else 7

        try:
            resp = await llm.complete(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER.format(destination=destination, origin=origin, days=days)}],
                response_format={"type": "json_object"}, agent="sustainability",
            )
            data = json.loads(resp)
        except Exception:  # noqa: BLE001
            data = {"flight_co2_kg": 0, "eco_tips": ["Choose direct flights", "Use public transit"], "carbon_offset_usd": 10, "sustainability_score": "medium"}

        return AgentResult(agent=self.slug, summary=f"Carbon: ~{data.get('flight_co2_kg', '?')}kg CO2 — offset ~${data.get('carbon_offset_usd', '?')}", data={"destination": destination, **data})
