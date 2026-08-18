"""Crowd Agent — tourist density, peak seasons, best times to visit.

Uses GDELT (event frequency as a proxy for tourism buzz) + LLM for
crowd prediction and optimal visit timing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm
from app.tools import gdelt

logger = logging.getLogger(__name__)

CROWD_SYSTEM = """You are Journava's Crowd Analysis agent. Predict tourist crowd levels.
Respond in JSON:
{"crowd_level": "low|medium|high|peak", "best_week": "week description",
 "avoid_periods": ["period1"], "reason": "explanation",
 "tip": "practical tip for avoiding crowds"}"""

CROWD_USER = """Destination: {destination}
Travel dates: {dates}
Recent news/tourism buzz (article count): {article_count}
Season context: {season}

Predict crowd levels and best visit timing."""


class CrowdAgent(BaseAgent):
    slug = "crowd"
    name = "Crowd"
    role = "Tourist density · peak seasons · best visit timing"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"
        dates = f"{request.start_date} to {request.end_date}" if request.start_date else "flexible"

        # GDELT tourism buzz (positive news = tourism interest)
        news_events = await gdelt.events(f"{destination} tourism travel", days=30)
        article_count = len(news_events)

        # Determine current season context
        season = "unknown"
        if request.start_date:
            month = request.start_date.month
            if month in (12, 1, 2):
                season = "Winter (Dec-Feb)"
            elif month in (3, 4, 5):
                season = "Spring (Mar-May)"
            elif month in (6, 7, 8):
                season = "Summer (Jun-Aug)"
            else:
                season = "Autumn (Sep-Nov)"

        try:
            response = await llm.complete(
                [
                    {"role": "system", "content": CROWD_SYSTEM},
                    {"role": "user", "content": CROWD_USER.format(
                        destination=destination,
                        dates=dates,
                        article_count=article_count,
                        season=season,
                    )},
                ],
                response_format={"type": "json_object"},
                agent="crowd",
            )
            crowd_info = json.loads(response)
        except Exception:  # noqa: BLE001
            crowd_info = {
                "crowd_level": "medium",
                "best_week": "Weekdays are generally less crowded",
                "avoid_periods": ["Public holidays"],
                "reason": "Insufficient data for precise prediction",
                "tip": "Book popular attractions in advance during peak season",
            }

        return AgentResult(
            agent=self.slug,
            summary=f"Crowd level: {crowd_info.get('crowd_level', 'unknown')} — {crowd_info.get('tip', '')}",
            data={
                "destination": destination,
                "crowd_level": crowd_info.get("crowd_level"),
                "best_week": crowd_info.get("best_week"),
                "avoid_periods": crowd_info.get("avoid_periods", []),
                "reason": crowd_info.get("reason"),
                "tip": crowd_info.get("tip"),
                "tourism_buzz_articles": article_count,
            },
        )
