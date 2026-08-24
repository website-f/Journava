"""Insurance Agent — travel insurance recommendations based on risk level."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Insurance agent. Recommend travel insurance coverage.
Respond in JSON:
{"recommended_coverage": ["medical", "trip_cancellation", "baggage"],
 "estimated_cost_usd": 50, "risk_factors": ["factor1"],
 "providers": ["provider1"], "notes": "important note"}"""

USER = "Destination: {destination}\nSafety level: {safety}\nTrip days: {days}\nRecommend insurance."


class InsuranceAgent(BaseAgent):
    slug = "insurance"
    name = "Insurance"
    role = "Travel insurance · coverage recommendations"

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
        safety = "safe"
        if context:
            risk_data = context.get("risk_advisory", {}).get("data", {})
            safety = risk_data.get("safety_level", "safe")

        try:
            resp = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": USER.format(destination=destination, safety=safety, days=days),
                    },
                ],
                response_format={"type": "json_object"},
                agent="insurance",
            )
            data = json.loads(resp)
        except Exception:  # noqa: BLE001
            data = {
                "recommended_coverage": ["medical", "trip_cancellation"],
                "estimated_cost_usd": 40,
                "notes": "Compare providers before purchasing.",
            }

        warnings = []
        if safety in ("caution", "dangerous"):
            warnings.append(
                "Higher-risk destination — comprehensive medical + evacuation coverage recommended."
            )

        # A place to actually compare & buy — the section listed provider names
        # with no way to reach them.
        from urllib.parse import quote_plus

        sources = [
            {"title": "Compare travel insurance (search)", "url": f"https://www.google.com/search?q={quote_plus('compare travel insurance ' + destination + ' online quote')}"},
        ]
        providers = data.get("providers") or []
        for name in providers[:5]:
            if isinstance(name, str) and name.strip():
                sources.append(
                    {"title": name.strip(), "url": f"https://www.google.com/search?q={quote_plus(name.strip() + ' travel insurance')}"}
                )

        return AgentResult(
            agent=self.slug,
            summary=f"Insurance coverage for {destination} ({safety})",
            warnings=warnings,
            data={"destination": destination, "safety_level": safety, **data, "sources": sources},
        )
