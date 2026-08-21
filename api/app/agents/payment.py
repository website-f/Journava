"""Payment Agent — payment methods, card acceptance, tipping culture.

Research-backed: real FX rate (Frankfurter) plus a Camofox crawl of local payment
culture (cards vs cash vs QR apps, tipping) with cited sources.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm
from app.tools import discover, frankfurter

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Payment agent. Provide payment advice for travelers, \
grounded in the RESEARCH provided (how people actually pay there).
Respond in JSON:
{"cards_accepted": true, "cash_needed": "for small vendors/markets",
 "tipping_pct": 10, "contactless": true, "mobile_pay": "Alipay/WeChat/Apple Pay/none",
 "atm_fees": "moderate", "local_currency": "USD", "notes": "payment tip"}
Be concrete about which QR/mobile wallet dominates locally — travellers need to know what to set up."""

USER = (
    "Destination: {destination}\nCurrency: {currency}\n\n"
    "RESEARCH (live web crawl):\n{research}\n\n"
    "Provide payment advice, especially how locals pay day to day."
)


class PaymentAgent(BaseAgent):
    slug = "payment"
    name = "Payment"
    role = "Payment methods · card acceptance · tipping"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"
        local_currency = profile.budget_currency

        self.emit("working", f"Researching how to pay in {destination}")
        rates, research = await _gather(destination, local_currency)

        try:
            resp = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": USER.format(
                            destination=destination,
                            currency=local_currency,
                            research=research["text"] or "(no live results — use best knowledge)",
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="payment",
            )
            data = json.loads(resp)
        except Exception:  # noqa: BLE001
            data = {
                "cards_accepted": True,
                "cash_needed": "Some vendors",
                "tipping_pct": 10,
                "notes": "Carry some local currency.",
            }

        fx_rate = rates.get(local_currency, 1.0) if rates else None
        sources = discover.source_links(research["sources"])
        return AgentResult(
            agent=self.slug,
            summary=f"Payment info for {destination}",
            data={
                "destination": destination,
                "fx_rate_myr_to_local": fx_rate,
                **data,
                "sources": sources,
            },
        )


async def _gather(destination: str, currency: str) -> tuple[Any, dict[str, Any]]:
    """Fetch the FX rate and payment-culture research concurrently."""
    return await asyncio.gather(
        frankfurter.rates("MYR"),
        discover.crawl_sources(
            [
                f"how to pay in {destination} cards cash mobile payment app tipping",
                f"{destination} tipping etiquette contactless ATM fees for tourists",
            ]
        ),
    )
