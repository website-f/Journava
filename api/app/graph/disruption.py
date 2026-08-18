"""Disruption recovery orchestrator (spec §3 "wow flow").

When a disruption hits, this re-runs the affected slice of the graph to rebuild
the trip autonomously. Every step publishes SSE events so the Agent Control
Center shows the recovery chain live — the "money shot" demo.

Cascade: Flight (rebook) → Itinerary (adjust days) → Budget (cost impact)
         → Chief (summarise the recovery plan)

Two things this module has to get right or the demo is theatre:

1. **Fresh inventory.** The recovery search must bypass the Redis cache. Serving
   the pre-disruption cache returns the cancelled flight as its own replacement,
   which makes "additional cost RM0" a cache artefact rather than a result.
2. **Honest cost.** The delta is computed against a comparable option, and a
   recovery that genuinely costs nothing says so for a reason — because the
   replacement was found at or below the original fare.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.agents import REGISTRY
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import sse

logger = logging.getLogger(__name__)

DisruptionType = Literal["flight_cancelled", "weather_alert", "budget_exceeded"]

#: Which agent leads recovery for each disruption kind.
_RECOVERY_LEAD: dict[str, str] = {
    "flight_cancelled": "flight",
    "weather_alert": "weather_risk",
    "budget_exceeded": "budget",
}

_DISRUPTION_MESSAGE: dict[str, str] = {
    "flight_cancelled": "Flight cancelled by airline — finding alternatives",
    "weather_alert": "Severe weather detected — re-routing trip",
    "budget_exceeded": "Budget threshold breached — adjusting options",
}


async def handle_disruption(
    disruption_type: DisruptionType,
    affected_agent: str,
    original_request: TripRequest,
    profile: TravelerProfile,
    original_results: dict[str, Any],
) -> dict[str, Any]:
    """Run the recovery cascade and return a recovery plan."""
    agents_activated: list[str] = []

    # --- 1. Announce the disruption ---
    sse.publish(
        affected_agent,
        "error",
        _DISRUPTION_MESSAGE.get(disruption_type, "Disruption detected"),
        data={"disruption_type": disruption_type},
    )

    lead = _RECOVERY_LEAD.get(disruption_type, "flight")

    # --- 2. Re-run the lead agent against *fresh* inventory ---
    sse.publish(lead, "working", "Searching alternatives (bypassing cache)")
    agents_activated.append(lead)

    # `bypass_cache` is what makes this a real re-search rather than a replay of
    # the results that existed before the disruption.
    lead_result: AgentResult = await REGISTRY[lead](
        original_request,
        profile,
        caused_by="chief",
        context={**original_results, "bypass_cache": True, "disruption": disruption_type},
    )
    new_lead_data = lead_result.model_dump(mode="json")
    sse.publish(
        lead,
        "active",
        f"Found {len(lead_result.options)} alternative option(s)",
    )

    recovery_context: dict[str, Any] = {**original_results, lead: new_lead_data}

    # --- 3. Itinerary first: it produces the items and nights Budget needs ---
    sse.publish("itinerary", "working", "Adjusting itinerary for the new schedule")
    agents_activated.append("itinerary")
    itinerary_result: AgentResult = await REGISTRY["itinerary"](
        original_request,
        profile,
        caused_by=lead,
        context=recovery_context,
    )
    new_itinerary_data = itinerary_result.model_dump(mode="json")
    recovery_context["itinerary"] = new_itinerary_data
    sse.publish(
        "itinerary",
        "active",
        f"Itinerary adjusted — {len(itinerary_result.items)} items",
    )

    # --- 4. Budget: cost impact of the rebuilt trip ---
    sse.publish("budget", "working", "Recalculating budget impact")
    agents_activated.append("budget")
    budget_result: AgentResult = await REGISTRY["budget"](
        original_request,
        profile,
        caused_by="itinerary",
        context=recovery_context,
    )
    new_budget_data = budget_result.model_dump(mode="json")
    recovery_context["budget"] = new_budget_data
    sse.publish("budget", "active", budget_result.summary)

    # --- 5. Chief summarises ---
    agents_activated.append("chief")
    currency = original_request.budget_currency or profile.budget_currency
    delta = _cost_delta(original_results.get(lead, {}), new_lead_data, currency=currency)

    summary = _summarise(delta, currency)
    sse.publish("chief", "active", summary, data=delta)

    return {
        "disruption_type": disruption_type,
        "recovery_plan": {
            lead: new_lead_data,
            "itinerary": new_itinerary_data,
            "budget": new_budget_data,
        },
        "additional_cost": (
            f"{currency} {delta['additional_cost']:.2f}"
            if delta["additional_cost"] is not None
            else "not comparable"
        ),
        "cost_detail": delta,
        "agents_activated": agents_activated,
        "summary": summary,
    }


def _summarise(delta: dict[str, Any], currency: str) -> str:
    """Phrase the outcome without overclaiming."""
    additional = delta["additional_cost"]
    if additional is None:
        return "Recovery plan ready — cost impact could not be compared"
    if additional <= 0:
        saved = abs(additional)
        if saved > 0:
            return f"Recovery plan ready — {currency} {saved:.2f} cheaper than the original"
        return f"Recovery plan ready — no additional cost ({currency} 0.00)"
    return f"Recovery plan ready — additional cost {currency} {additional:.2f}"


def _cost_delta(
    original: dict[str, Any],
    replacement: dict[str, Any],
    *,
    currency: str,
) -> dict[str, Any]:
    """Compare the cheapest comparable option before and after recovery.

    Returns `additional_cost=None` when either side has no priced option — a
    missing comparison is reported as such rather than silently becoming zero.
    """
    before = _cheapest(original)
    after = _cheapest(replacement)

    if before is None or after is None:
        return {
            "original_cost": before,
            "replacement_cost": after,
            "additional_cost": None,
            "currency": currency,
            "comparable": False,
        }

    return {
        "original_cost": round(before, 2),
        "replacement_cost": round(after, 2),
        "additional_cost": round(after - before, 2),
        "currency": currency,
        "comparable": True,
    }


def _cheapest(result: dict[str, Any]) -> float | None:
    """Cheapest priced option in a result, or None when nothing is priced."""
    prices = [
        float(option["price_amount"])
        for option in result.get("options", []) or []
        if option.get("price_amount") is not None
    ]
    return min(prices) if prices else None
