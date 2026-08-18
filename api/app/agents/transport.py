"""Transport Agent — ground transport, inter-city routes, local transit."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Transport agent. Recommend ground transport options.
Respond in JSON:
{"airport_transfer": [{"mode": "taxi|train|bus", "cost_usd": 0, "duration_min": 30}],
 "inter_city": [{"mode": "train|bus|domestic_flight", "route": "city A to city B"}],
 "local_transit": {"primary": "metro|bus|tram", "day_pass_usd": 5, "apps": ["Grab", "Uber"]},
 "tips": "practical transport tip"}"""

USER = "Destination: {destination}\nTrip days: {days}\nRecommend ground transport."


class TransportAgent(BaseAgent):
    slug = "transport"
    name = "Transport"
    role = "Ground transport · inter-city · local transit"

    async def run(self, request: TripRequest, profile: TravelerProfile, *, context: dict[str, Any] | None = None) -> AgentResult:
        destination = request.destination or "unknown"
        days = (request.end_date - request.start_date).days if request.start_date and request.end_date else 7

        try:
            resp = await llm.complete(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER.format(destination=destination, days=days)}],
                response_format={"type": "json_object"}, agent="transport",
            )
            data = json.loads(resp)
        except Exception:  # noqa: BLE001
            data = {"airport_transfer": [{"mode": "taxi", "cost_usd": 30, "duration_min": 45}],
                    "local_transit": {"primary": "taxi/rideshare", "apps": ["Grab"]}, "tips": "Use rideshare apps for convenience."}

        return AgentResult(agent=self.slug, summary=f"Transport options for {destination}", data={"destination": destination, **data})
