"""Disruption recovery orchestrator (spec §3 "wow flow").

When a flight disruption hits, this module re-runs a subset of agents to
autonomously rebuild the trip. Each step publishes SSE events so the Agent
Control Center shows the recovery chain live — this is the "money shot" demo.

Cascade: Flight (rebook) → Budget (cost impact) → Itinerary (adjust days)
         → Chief (summarise recovery plan)
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Literal

from app.agents import REGISTRY
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import sse

logger = logging.getLogger(__name__)


async def handle_disruption(
    disruption_type: Literal["flight_cancelled", "weather_alert", "budget_exceeded"],
    affected_agent: str,
    original_request: TripRequest,
    profile: TravelerProfile,
    original_results: dict[str, Any],
) -> dict[str, Any]:
    """Run the recovery cascade and return a recovery plan.

    Each agent in the chain emits SSE events so the UI shows live progress.
    """
    agents_activated: list[str] = []

    # --- 1. Announce the disruption ---
    disruption_messages = {
        "flight_cancelled": "Flight cancelled by airline — finding alternatives",
        "weather_alert": "Severe weather detected — re-routing trip",
        "budget_exceeded": "Budget threshold breached — adjusting options",
    }
    sse.publish(affected_agent, "error", disruption_messages.get(disruption_type, "Disruption detected"))

    # --- 2. Re-run Flight Agent (find next available) ---
    sse.publish("flight", "working", "Searching alternative flights (next available)")
    agents_activated.append("flight")

    flight_agent = REGISTRY["flight"]
    flight_result: AgentResult = await flight_agent(original_request, profile, caused_by="chief")
    new_flight_data = flight_result.model_dump(mode="json")

    sse.publish("flight", "active", f"Found {len(flight_result.options)} alternative flights")

    # --- 3. Re-run Budget Agent (check cost impact) ---
    sse.publish("budget", "working", "Recalculating budget impact")
    agents_activated.append("budget")

    # Build a context with the new flight results for the budget agent
    recovery_context = {**original_results, "flight": new_flight_data}
    budget_agent = REGISTRY["budget"]
    budget_result: AgentResult = await budget_agent(
        original_request, profile, caused_by="flight", context=recovery_context,
    )
    new_budget_data = budget_result.model_dump(mode="json")

    sse.publish("budget", "active", budget_result.summary)

    # --- 4. Re-run Itinerary Agent (adjust affected days) ---
    sse.publish("itinerary", "working", "Adjusting itinerary for new flight schedule")
    agents_activated.append("itinerary")

    recovery_context["budget"] = new_budget_data
    itinerary_agent = REGISTRY["itinerary"]
    itinerary_result: AgentResult = await itinerary_agent(
        original_request, profile, caused_by="flight", context=recovery_context,
    )

    sse.publish("itinerary", "active", f"Itinerary adjusted — {len(itinerary_result.items)} items")

    # --- 5. Chief summarises the recovery plan ---
    agents_activated.append("chief")

    # Calculate additional cost
    original_flight_cost = _extract_min_cost(original_results.get("flight", {}))
    new_flight_cost = _extract_min_cost(new_flight_data)
    additional_cost = max(0.0, round(new_flight_cost - original_flight_cost, 2))
    currency = original_request.budget_currency or profile.budget_currency

    # --- 6. Publish recovery summary ---
    if additional_cost == 0:
        cost_msg = "Recovery plan ready — additional cost RM0"
    else:
        cost_msg = f"Recovery plan ready — additional cost {currency} {additional_cost}"

    sse.publish("chief", "active", cost_msg)

    return {
        "disruption_type": disruption_type,
        "recovery_plan": {
            "flight": new_flight_data,
            "budget": new_budget_data,
            "itinerary": itinerary_result.model_dump(mode="json"),
        },
        "additional_cost": f"{currency} {additional_cost}",
        "agents_activated": agents_activated,
        "summary": cost_msg,
    }


def _extract_min_cost(flight_result: dict[str, Any]) -> float:
    """Find the cheapest option price in a flight result."""
    options = flight_result.get("options", [])
    if not options:
        return 0.0
    prices = [float(o.get("price_amount", 0) or 0) for o in options if o.get("price_amount")]
    return min(prices) if prices else 0.0
