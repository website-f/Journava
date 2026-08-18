"""Chief Agent — orchestration, delegation, reconciliation (spec §4.1).

Parses the user's free-form goal into structured TripRequest fields via LLM,
then delegates to the LangGraph supervisor which fans out to the specialists.

The `enriched` dict this agent returns is not advisory: the supervisor folds it
into the request before Tier 1 runs (`apply_chief_enrichment`). The resolved
fields are also mirrored at the top level of `data` so the UI and the disruption
endpoint can read them without knowing this agent's internal shape.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.goal_parser import parse_goal
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

        # --- Rule-based parse first: it is free, instant, and never unavailable.
        # It also acts as the backstop for whatever the model leaves null.
        rule_parsed = parse_goal(request.goal)
        if rule_parsed:
            logger.info("Chief rule-parsed goal: %s", rule_parsed)

        # --- LLM goal parsing ---
        parsed: dict[str, Any] = {}
        llm_available = True
        try:
            messages = chief_messages(request, profile)
            raw = await complete(messages, response_format={"type": "json_object"}, agent="chief")
            parsed = json.loads(raw)
            logger.info("Chief LLM-parsed goal: %s", parsed)
        except (LLMUnavailableError, json.JSONDecodeError, Exception) as exc:
            llm_available = False
            logger.warning("Chief LLM parsing failed (%s), using the rule parse", exc)
            self.emit(
                "waiting",
                f"No model available ({type(exc).__name__}) — parsed the request directly",
            )

        # The model wins where it answered; the rule parse fills the rest. Doing
        # it in that order matters: an LLM handles phrasing rules never will, but
        # a null from the model is not an answer, and the text often still has one.
        merged: dict[str, Any] = {**rule_parsed}
        for key, value in parsed.items():
            if value not in (None, "", [], {}):
                merged[key] = value

        # Fill gaps in the request; never overwrite what the user typed explicitly.
        enriched: dict[str, Any] = {}
        if merged.get("origin") and not request.origin:
            enriched["origin"] = merged["origin"]
        if merged.get("destination") and not request.destination:
            enriched["destination"] = merged["destination"]
        if merged.get("start_date") and not request.start_date:
            enriched["start_date"] = merged["start_date"]
        if merged.get("end_date") and not request.end_date:
            enriched["end_date"] = merged["end_date"]
        if merged.get("travellers") and request.travellers == 1:
            enriched["travellers"] = merged["travellers"]
        if merged.get("budget_amount") and not request.budget_amount:
            enriched["budget_amount"] = merged["budget_amount"]
        if merged.get("budget_currency") and request.budget_currency == "MYR":
            enriched["budget_currency"] = merged["budget_currency"]
        if merged.get("pace") and not request.pace:
            enriched["pace"] = merged["pace"]

        # A home airport is a reasonable origin for a one-way ask that named only
        # a destination — the traveller rarely repeats where they live.
        if not enriched.get("origin") and not request.origin and profile.home_airport:
            enriched["origin"] = profile.home_airport

        # The request the specialists will actually receive, once the supervisor
        # applies `enriched`. Mirrored into `data` so every consumer — the
        # Command Center card, My Trip, the disruption endpoint — reads one
        # canonical shape instead of digging into `data["parsed"]`.
        resolved: dict[str, Any] = {**request.model_dump(mode="json"), **enriched}
        dest = resolved.get("destination") or "unknown"

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
                "rule_parsed": rule_parsed,
                "enriched": enriched,
                # Which parser actually answered — surfaced so a placeholder
                # result is traceable to a missing model rather than a mystery.
                "parse_source": ("llm+rules" if llm_available and parsed else "rules_only"),
                "llm_available": llm_available,
                "interests_detected": merged.get("interests_detected", []),
                "preferred_departure_window": merged.get("preferred_departure_window"),
                "max_connections_detected": merged.get("max_connections"),
                # --- resolved trip fields (canonical, read by UI + recovery) ---
                "resolved_request": resolved,
                "destination": resolved.get("destination"),
                "origin": resolved.get("origin"),
                "start_date": resolved.get("start_date"),
                "end_date": resolved.get("end_date"),
                "travellers": resolved.get("travellers", 1),
                "budget_amount": resolved.get("budget_amount"),
                "budget_currency": resolved.get("budget_currency", "MYR"),
            },
        )
