"""Shopping Agent — local markets, duty-free, souvenirs, bargaining tips.

Research-backed: crawls Camofox for what people actually buy and where locals
recommend, cites its sources, and attaches public TikTok clips (embedded) so the
traveller can see the place before going.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, Option, TravelerProfile, TripRequest
from app.core import llm
from app.tools import discover

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Shopping agent. Recommend where and what to shop, \
grounded in the RESEARCH provided (real recommendations, not memory).
Respond in JSON:
{"markets": [{"name": "market/mall/street", "area": "district", "specialty": "what to buy here", "bargaining": "yes|no", "budget_usd": 20}],
 "must_buy": ["specific item locals/tourists recommend"],
 "where_locals_go": "the spots locals recommend over tourist traps",
 "duty_free": "airport duty-free info",
 "scam_warnings": ["warning"]}
Prefer specific, named places from the research over generic advice."""

USER = (
    "Destination: {destination}\n"
    "Budget: {budget}\n\n"
    "RESEARCH (live web crawl — reddit/blogs/guides):\n{research}\n\n"
    "Recommend where and what to shop, favouring what real people recommend."
)


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

        self.emit("working", f"Researching shopping in {destination}")
        research, videos = await _gather(destination)

        try:
            resp = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": USER.format(
                            destination=destination,
                            budget=budget,
                            research=research["text"] or "(no live results — use best knowledge)",
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="shopping",
            )
            data = json.loads(resp)
            if not isinstance(data, dict):
                raise TypeError("LLM did not return a JSON object")
        except Exception:  # noqa: BLE001
            data = {
                "markets": [],
                "must_buy": [],
                "duty_free": "Check airport duty-free on departure",
                "scam_warnings": ["Always verify prices"],
            }

        options = [
            Option(
                id=f"shop-{i}",
                kind="activity",
                title=m.get("name", ""),
                reasoning=" · ".join(
                    bit for bit in (m.get("area"), m.get("specialty")) if bit
                ),
            )
            for i, m in enumerate(data.get("markets", []))
            if isinstance(m, dict)
        ]

        sources = discover.source_links(research["sources"])
        if sources or videos:
            self.emit(
                "active",
                f"Shopping: {len(sources)} source(s), {len(videos)} clip(s)",
            )

        return AgentResult(
            agent=self.slug,
            summary=f"Shopping guide for {destination}",
            options=options,
            data={"destination": destination, **data, "sources": sources, "videos": videos},
        )


async def _gather(destination: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Crawl shopping research and TikTok clips concurrently."""
    research, videos = await asyncio.gather(
        discover.crawl_sources(
            [
                f"best shopping in {destination} what to buy where locals recommend",
                f"{destination} shopping guide reddit what to buy souvenirs",
            ]
        ),
        discover.tiktok_reviews(f"{destination} shopping what to buy haul"),
    )
    return research, videos
