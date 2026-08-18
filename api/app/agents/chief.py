"""Chief Agent — orchestration, delegation, reconciliation (spec §4.1).

Phase 1: parses the user's free-form goal into structured TripRequest fields via
LLM, then delegates to the LangGraph supervisor which fans out to specialists.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts import chief_messages
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core.llm import LLMUnavailableError, complete

logger = logging.getLogger(__name__)


class ChiefAgent(BaseAgent):
    slug = "chief"
    name = "Chief"
    role = "Orchestration & reconciliation"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        delegated = ["flight", "hotel", "research", "weather_risk"]

        # --- LLM goal parsing ---
        parsed: dict[str, Any] = {}
        try:
            messages = chief_messages(request, profile)
            raw = await complete(messages, response_format={"type": "json_object"})
            parsed = json.loads(raw)
            logger.info("Chief parsed goal: %s", parsed)
        except (LLMUnavailableError, json.JSONDecodeError, Exception) as exc:
            logger.warning("Chief LLM parsing failed (%s), using raw goal fields", exc)
            self.emit("waiting", f"LLM unavailable ({type(exc).__name__}), using provided fields")

        # Merge LLM-parsed fields into the request (fill gaps, never overwrite user-provided)
        enriched: dict[str, Any] = {}
        if parsed.get("origin") and not request.origin:
            enriched["origin"] = parsed["origin"]
        if parsed.get("destination") and not request.destination:
            enriched["destination"] = parsed["destination"]
        if parsed.get("start_date") and not request.start_date:
            enriched["start_date"] = parsed["start_date"]
        if parsed.get("end_date") and not request.end_date:
            enriched["end_date"] = parsed["end_date"]
        if parsed.get("travellers") and request.travellers == 1:
            enriched["travellers"] = parsed["travellers"]
        if parsed.get("budget_amount") and not request.budget_amount:
            enriched["budget_amount"] = parsed["budget_amount"]
        if parsed.get("budget_currency") and request.budget_currency == "MYR":
            enriched["budget_currency"] = parsed["budget_currency"]

        # Emit a summary of what was understood
        dest = enriched.get("destination") or request.destination or "unknown"
        self.emit(
            "working",
            f"Parsed goal → {dest}",
            data={"parsed": parsed, "enriched": enriched},
        )
        self.emit(
            "working",
            f"Delegating to {len(delegated)} specialists",
            data={"delegated": delegated},
        )

        return AgentResult(
            agent=self.slug,
            summary=f"Plan orchestrated for: {dest}",
            data={
                "delegated": delegated,
                "parsed": parsed,
                "enriched": enriched,
                "interests_detected": parsed.get("interests_detected", []),
            },
        )
