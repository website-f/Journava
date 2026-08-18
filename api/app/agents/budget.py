"""Budget Agent — cost tracking + FX; keeps the trip in budget (spec §4.6).

Phase 2: wires Frankfurter FX (no key) + aggregates costs from upstream agent
results (flight, hotel, itinerary). Budget is a soft cap (§7.5) — it shapes
ranking but never hard-filters options.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, Scope, TravelerProfile, TripRequest
from app.tools.frankfurter import rates as fx_rates

logger = logging.getLogger(__name__)


class BudgetAgent(BaseAgent):
    slug = "budget"
    name = "Budget"
    role = "Cost tracking · FX"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        currency = request.budget_currency or profile.budget_currency
        budget_amount = float(request.budget_amount) if request.budget_amount else None

        self.emit("working", f"Calculating budget in {currency}")

        # Fetch FX rates (relative to budget currency)
        fx = await fx_rates(currency)

        # Aggregate costs from upstream results
        breakdown = self._aggregate_costs(context or {}, fx, currency)

        spent = breakdown["total_estimate"]
        over_budget = False
        remaining = None
        if budget_amount is not None:
            remaining = round(budget_amount - spent, 2)
            over_budget = spent > budget_amount

        # Build summary
        if budget_amount:
            status = "OVER BUDGET" if over_budget else f"{remaining} {currency} remaining"
            summary = f"Estimate: {spent} {currency} / {budget_amount} {currency} — {status}"
        else:
            summary = f"Estimate: {spent} {currency} (no budget cap set)"

        if over_budget:
            self.emit("monitoring", f"Trip is over budget by {abs(remaining)} {currency}")
        else:
            self.emit("active", summary)

        return AgentResult(
            agent=self.slug,
            summary=summary,
            warnings=[f"Trip exceeds budget by {abs(remaining)} {currency}"] if over_budget else [],
            data={
                "budget_amount": budget_amount,
                "currency": currency,
                "spent_estimate": spent,
                "remaining": remaining,
                "over_budget": over_budget,
                "breakdown": breakdown,
                "fx_rates": dict(list((fx or {}).items())[:10]) if fx else None,
            },
        )

    @staticmethod
    def _aggregate_costs(
        results: dict[str, Any],
        fx: dict[str, float] | None,
        target_currency: str,
    ) -> dict[str, Any]:
        """Sum cheapest options from each upstream agent."""
        flight_cost = _extract_cheapest(results.get("flight", {}), fx, target_currency)
        hotel_cost = _extract_cheapest(results.get("hotel", {}), fx, target_currency)
        activity_cost = _sum_itinerary_costs(results.get("itinerary", {}), fx, target_currency)

        # Hotels are per-night; estimate nights from itinerary items or default to 7
        nights = _estimate_nights(results.get("itinerary", {}))
        hotel_total = round(hotel_cost * nights, 2)

        total = round(flight_cost + hotel_total + activity_cost, 2)

        return {
            "flights": flight_cost,
            "hotels_per_night": hotel_cost,
            "hotels_total": hotel_total,
            "nights": nights,
            "activities": activity_cost,
            "total_estimate": total,
        }


def _convert(value: float | None, from_currency: str | None, fx: dict[str, float] | None, target: str) -> float:
    """Convert a value to the target currency using FX rates."""
    if value is None:
        return 0.0
    if not fx or not from_currency:
        return float(value)
    if from_currency.upper() == target.upper():
        return float(value)
    rate = fx.get(from_currency.upper())
    if rate is None:
        return float(value)  # Can't convert, assume same currency
    return round(float(value) * rate, 2)


def _extract_cheapest(result: dict[str, Any], fx: dict[str, float] | None, target: str) -> float:
    """Find the cheapest option in a result set and return its price in target currency."""
    options = result.get("options", [])
    if not options:
        return 0.0
    cheapest = float("inf")
    for opt in options:
        price = opt.get("price_amount")
        if price is not None:
            curr = opt.get("price_currency", target)
            converted = _convert(float(price), curr, fx, target)
            cheapest = min(cheapest, converted)
    return round(cheapest, 2) if cheapest != float("inf") else 0.0


def _sum_itinerary_costs(result: dict[str, Any], fx: dict[str, float] | None, target: str) -> float:
    """Sum all itinerary item costs."""
    items = result.get("items", [])
    total = 0.0
    for item in items:
        cost = item.get("cost_amount")
        if cost is not None:
            curr = item.get("cost_currency", target)
            total += _convert(float(cost), curr, fx, target)
    return round(total, 2)


def _estimate_nights(itinerary_result: dict[str, Any]) -> int:
    """Estimate trip nights from itinerary day indices."""
    items = itinerary_result.get("items", [])
    if not items:
        return 7  # default
    days = {item.get("day_index", 1) for item in items if isinstance(item, dict)}
    return max(1, len(days))
