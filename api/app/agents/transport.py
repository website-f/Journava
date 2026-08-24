"""Transport Agent — ground transport, inter-city routes, local transit.

Research-backed: crawls Camofox for how people actually get around the
destination (and how they pay — cash / card / contactless / which app), grounds
the LLM in what it read, and cites its sources.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote_plus

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm
from app.tools import discover

logger = logging.getLogger(__name__)


def _booking_links(destination: str) -> list[dict[str, str]]:
    """Where to actually BUY tickets/passes — the transport section had only
    reference blogs, no purchase path. These search URLs always resolve to real
    bookable inventory for the destination."""
    q = quote_plus(destination)
    return [
        {"title": f"Klook — {destination} transport, passes & transfers", "url": f"https://www.klook.com/en-US/search/?query={q}"},
        {"title": "12Go — trains, buses & ferries", "url": f"https://12go.asia/en?z=&people=1&query={q}"},
        {"title": f"Book {destination} tickets (search)", "url": f"https://www.google.com/search?q={quote_plus('book ' + destination + ' transport tickets pass online')}"},
    ]

SYSTEM = """You are Journava's Transport agent. Recommend how to get around the \
destination, grounded in the RESEARCH provided (don't rely on memory alone).
Respond in JSON:
{"airport_transfer": [{"mode": "taxi|train|bus|rideshare", "cost_usd": 0, "duration_min": 30, "how_to_pay": "cash|card|contactless|app"}],
 "inter_city": [{"mode": "train|bus|domestic_flight", "route": "city A to city B", "how_to_pay": "card|app"}],
 "local_transit": {"primary": "metro|bus|tram|rideshare", "day_pass_usd": 5, "payment": "how locals pay — transit card / contactless / cash / which app", "apps": ["Grab", "Uber"]},
 "tips": "practical transport tip"}
Always fill "how_to_pay"/"payment" concretely (e.g. 'Alipay/WeChat QR', 'contactless Visa', 'Tianfutong transit card', 'cash only') — the traveller needs to know what to bring."""

USER = (
    "Destination: {destination}\n"
    "Trip days: {days}\n\n"
    "RESEARCH (live web crawl — use it, cite nothing you didn't see):\n{research}\n\n"
    "Recommend ground transport and, importantly, how to pay for each."
)


class TransportAgent(BaseAgent):
    slug = "transport"
    name = "Transport"
    role = "Ground transport · inter-city · local transit"

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

        self.emit("working", f"Researching how to get around {destination}")
        research = await discover.crawl_sources(
            [
                f"how to get around {destination} public transport guide",
                f"{destination} how to pay for transport metro card contactless cash app",
                f"{destination} airport to city centre transfer options cost",
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
                            days=days,
                            research=research["text"] or "(no live results — use best knowledge)",
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="transport",
            )
            data = json.loads(resp)
            if not isinstance(data, dict):
                raise TypeError("LLM did not return a JSON object")
        except Exception:  # noqa: BLE001
            data = {
                "airport_transfer": [
                    {"mode": "taxi", "cost_usd": 30, "duration_min": 45, "how_to_pay": "card or app"}
                ],
                "local_transit": {"primary": "taxi/rideshare", "payment": "app", "apps": ["Grab"]},
                "tips": "Use rideshare apps for convenience.",
            }

        # Booking links first (guaranteed, actionable) then crawled references.
        booking = _booking_links(destination)
        sources = booking + discover.source_links(research["sources"])
        self.emit("active", f"Transport: {len(booking)} booking links + grounded sources")

        return AgentResult(
            agent=self.slug,
            summary=f"Transport options for {destination}",
            data={"destination": destination, **data, "booking_links": booking, "sources": sources},
        )
