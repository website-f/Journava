"""Disruption recovery honesty (spec §3 "wow flow").

The demo's headline is "additional cost RM0". That has to be a measurement, not
an artefact: the recovery search previously hit the same Redis key as the original
plan, so it returned the cancelled flight as its own replacement and the delta was
always exactly zero.
"""

from __future__ import annotations

import pytest

from app.agents.schemas import TravelerProfile, TripRequest
from app.brain.trip_store import reconstruct_request
from app.graph.disruption import _cheapest, _cost_delta, handle_disruption

pytestmark = pytest.mark.usefixtures("stub_llm", "no_network", "no_cache", "memory_brain")


def option(price):
    return {"price_amount": price, "price_currency": "MYR"}


def test_cheapest_ignores_unpriced_options():
    assert _cheapest({"options": [option(500), option(None), option(300)]}) == 300.0
    assert _cheapest({"options": [option(None)]}) is None
    assert _cheapest({"options": []}) is None
    assert _cheapest({}) is None


def test_cost_delta_reports_a_real_increase():
    delta = _cost_delta({"options": [option(2000)]}, {"options": [option(2350)]}, currency="MYR")
    assert delta["comparable"] is True
    assert delta["additional_cost"] == pytest.approx(350.0)


def test_cost_delta_reports_a_saving_as_negative():
    delta = _cost_delta({"options": [option(2000)]}, {"options": [option(1800)]}, currency="MYR")
    assert delta["additional_cost"] == pytest.approx(-200.0)


def test_incomparable_prices_are_not_reported_as_zero():
    """A missing price must surface as "not comparable", never as a free recovery."""
    delta = _cost_delta({"options": []}, {"options": [option(1800)]}, currency="MYR")
    assert delta["comparable"] is False
    assert delta["additional_cost"] is None


async def test_recovery_bypasses_the_cache(monkeypatch):
    """The lead agent must be told to re-search, not replay cached inventory."""
    seen: list[dict] = []

    from app.agents import REGISTRY

    original = REGISTRY["flight"].__class__.__call__

    async def spy(self, request, profile, *, caused_by=None, context=None):
        if self.slug == "flight":
            seen.append(context or {})
        return await original(self, request, profile, caused_by=caused_by, context=context)

    monkeypatch.setattr(REGISTRY["flight"].__class__, "__call__", spy)

    await handle_disruption(
        "flight_cancelled",
        "flight",
        TripRequest(goal="recovery", destination="Venice"),
        TravelerProfile(),
        {"flight": {"options": [option(2000)]}},
    )

    assert seen, "the flight agent was never re-run"
    assert seen[0].get("bypass_cache") is True


async def test_recovery_cascade_order_and_payload():
    """Itinerary before budget, and the response carries the cost breakdown."""
    recovery = await handle_disruption(
        "flight_cancelled",
        "flight",
        TripRequest(goal="recovery", destination="Venice"),
        TravelerProfile(),
        {"flight": {"options": [option(2000)]}},
    )

    assert recovery["agents_activated"] == ["flight", "itinerary", "budget", "chief"]
    assert "cost_detail" in recovery
    assert set(recovery["recovery_plan"]) == {"flight", "itinerary", "budget"}


async def test_weather_disruption_leads_with_the_weather_agent():
    recovery = await handle_disruption(
        "weather_alert",
        "weather_risk",
        TripRequest(goal="recovery", destination="Venice"),
        TravelerProfile(),
        {},
    )
    assert recovery["agents_activated"][0] == "weather_risk"


# --------------------------------------------------------------------------- #
# Request reconstruction
# --------------------------------------------------------------------------- #


def test_reconstruct_reads_the_canonical_mirror():
    """`resolved_request` is where the Chief puts the fields recovery needs."""
    request = reconstruct_request(
        {
            "chief": {
                "data": {
                    "resolved_request": {
                        "destination": "Venice",
                        "origin": "KUL",
                        "travellers": 2,
                        "budget_amount": 8000,
                        "budget_currency": "MYR",
                        "start_date": "2026-09-01",
                        "end_date": "2026-09-08",
                    }
                }
            }
        },
        goal="Recovery from flight_cancelled",
    )
    assert request.destination == "Venice"
    assert request.travellers == 2
    assert request.goal == "Recovery from flight_cancelled"


def test_reconstruct_falls_back_to_top_level_fields():
    """Older snapshots and the demo trip mirror fields at the top level."""
    request = reconstruct_request({"chief": {"data": {"destination": "Rome", "travellers": 3}}})
    assert request.destination == "Rome"
    assert request.travellers == 3


def test_reconstruct_survives_an_empty_trip():
    request = reconstruct_request({}, goal="cold start")
    assert request.goal == "cold start"
    assert request.destination is None
