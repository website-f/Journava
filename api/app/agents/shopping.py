"""Shopping Agent — local markets, duty-free, souvenirs, bargaining tips."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, Option, TravelerProfile, TripRequest
from app.core import llm

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Shopping agent. Recommend shopping experiences.
Respond in JSON:
{"markets": [{"name": "market", "specialty": "items", "bargaining": "yes|no", "budget_usd": 20}],
 "duty_free": "airport duty-free info", "must_buy": ["item1", "item2"],
 "scam_warnings": ["warning1"]}"""

USER = "Destination: {destination}\nBudget: {budget}\nRecommend shopping experiences."


class ShoppingAgent(BaseAgent):
    slug = "shopping"
    name = "Shopping"
    role = "Markets · duty-free · souvenirs · bargaining"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"
        budget = str(request.budget_amount) if request.budget_amount else "moderate"

        try:
            resp = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": USER.format(destination=destination, budget=budget),
                    },
                ],
                response_format={"type": "json_object"},
                agent="shopping",
            )
            data = json.loads(resp)
        except Exception:  # noqa: BLE001
            data = {
                "markets": [],
                "duty_free": "Check airport duty-free on departure",
                "must_buy": [],
                "scam_warnings": ["Always verify prices"],
            }

        options = [
            Option(
                id=f"shop-{i}",
                kind="activity",
                title=m.get("name", ""),
                reasoning=m.get("specialty", ""),
            )
            for i, m in enumerate(data.get("markets", []))
        ]
        return AgentResult(
            agent=self.slug,
            summary=f"Shopping guide for {destination}",
            options=options,
            data={"destination": destination, **data},
        )
