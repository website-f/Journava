"""Payment Agent — payment methods, card acceptance, tipping culture."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm
from app.tools import frankfurter

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Payment agent. Provide payment advice for travelers.
Respond in JSON:
{"cards_accepted": true, "cash_needed": "for small vendors/markets",
 "tipping_pct": 10, "contactless": true, "atm_fees": "moderate",
 "local_currency": "USD", "notes": "payment tip"}"""

USER = "Destination: {destination}\nCurrency: {currency}\nProvide payment advice."


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
        # Get FX rate if available
        rates = await frankfurter.rates("MYR")
        local_currency = profile.budget_currency

        try:
            resp = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": USER.format(destination=destination, currency=local_currency),
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
        return AgentResult(
            agent=self.slug,
            summary=f"Payment info for {destination}",
            data={"destination": destination, "fx_rate_myr_to_local": fx_rate, **data},
        )
