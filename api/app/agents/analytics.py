"""Analytics Agent — trip statistics, optimization tips, data-driven insights."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Analytics agent. Provide data-driven trip optimization.
Respond in JSON:
{"insights": [{"metric": "name", "value": "value", "tip": "optimization tip"}],
 "optimization_score": 0.0-1.0, "summary": "overall assessment"}"""

USER = "Destination: {destination}\nDays: {days}\nBudget: {budget} {currency}\nProvide optimization insights."


class AnalyticsAgent(BaseAgent):
    slug = "analytics"
    name = "Analytics"
    role = "Trip statistics · optimization · insights"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"
        days = (
            (request.end_date - request.start_date).days
            if request.start_date and request.end_date
            else 7
        )
        budget = str(request.budget_amount) if request.budget_amount else "flexible"

        try:
            resp = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": USER.format(
                            destination=destination,
                            days=days,
                            budget=budget,
                            currency=request.budget_currency,
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="analytics",
            )
            data = json.loads(resp)
        except Exception:  # noqa: BLE001
            data = {
                "insights": [
                    {
                        "metric": "Daily budget",
                        "value": f"{budget} {request.budget_currency}",
                        "tip": "Track spending daily",
                    }
                ],
                "optimization_score": 0.7,
                "summary": "Monitor and adjust as needed.",
            }

        return AgentResult(
            agent=self.slug,
            summary=data.get("summary", f"Analytics for {destination}"),
            data={"destination": destination, **data},
        )
