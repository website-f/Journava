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

CRITICAL: "local_currency" is the currency spent AT THE DESTINATION (its own
national currency, ISO-4217 code) — e.g. Turkey → TRY, Japan → JPY, UAE → AED.
It is NOT the traveller's home currency. Get this right.

Respond in JSON:
{"cards_accepted": true, "cash_needed": "for small vendors/markets",
 "tipping_pct": 10, "contactless": true, "mobile_pay": "Alipay/WeChat/Apple Pay/none",
 "atm_fees": "moderate", "local_currency": "TRY", "notes": "payment tip"}
Be concrete about which QR/mobile wallet dominates locally — travellers need to know what to set up."""

USER = (
    "Destination: {destination}\nTraveller's home currency: {home_currency}\n\n"
    "RESEARCH (live web crawl):\n{research}\n\n"
    "Provide payment advice, especially how locals pay day to day. Set "
    "local_currency to the DESTINATION's own currency code (not the home currency)."
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
        home_currency = (profile.budget_currency or "MYR").upper()

        self.emit("working", f"Researching how to pay in {destination}")
        rates, research = await _gather(destination, home_currency)

        try:
            resp = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": USER.format(
                            destination=destination,
                            home_currency=home_currency,
                            research=research["text"] or "(no live results — use best knowledge)",
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="payment",
            )
            data = json.loads(resp)
            if not isinstance(data, dict):
                raise TypeError("LLM did not return a JSON object")
        except Exception:  # noqa: BLE001
            data = {
                "cards_accepted": True,
                "cash_needed": "Some vendors",
                "tipping_pct": 10,
                "notes": "Carry some local currency.",
            }

        # The destination's own currency (from the LLM) drives the FX rate: how
        # much of the LOCAL currency the traveller gets per unit of home currency.
        local_ccy = str(data.get("local_currency") or "").upper()
        fx_rate = None
        if rates and local_ccy and local_ccy != home_currency:
            fx_rate = rates.get(local_ccy)  # base=home → 1 home = fx_rate local
        elif local_ccy == home_currency:
            fx_rate = 1.0

        sources = discover.source_links(research["sources"])
        return AgentResult(
            agent=self.slug,
            summary=f"Payment info for {destination}",
            data={
                "destination": destination,
                "home_currency": home_currency,
                "local_currency": local_ccy or None,
                "fx_rate": fx_rate,  # 1 {home} = {fx_rate} {local}
                **{k: v for k, v in data.items() if k != "local_currency"},
                "sources": sources,
            },
        )


async def _gather(destination: str, home_currency: str) -> tuple[Any, dict[str, Any]]:
    """Fetch the home-currency FX table and payment-culture research concurrently."""
    return await asyncio.gather(
        frankfurter.rates(home_currency),
        discover.crawl_sources(
            [
                f"how to pay in {destination} cards cash mobile payment app tipping",
                f"{destination} tipping etiquette contactless ATM fees for tourists",
            ]
        ),
    )
