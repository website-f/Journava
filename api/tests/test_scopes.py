"""Scoping — the answer must match the size of the question.

The regression this guards: *"cheap flights from KLIA to BKI"* ran all 21 agents
and returned visa rules, embassy numbers and carbon estimates alongside three
fares. A scope is what keeps the work proportionate.
"""

from __future__ import annotations

import pytest

from app.agents.schemas import TravelerProfile, TripRequest
from app.graph import scopes, supervisor

pytestmark = pytest.mark.usefixtures("stub_llm", "no_network", "no_cache", "memory_brain")


def test_every_scope_starts_with_chief_and_ends_with_memory():
    """Chief resolves the goal; memory closes the loop. Both are non-negotiable."""
    for scope in scopes.SCOPES.values():
        resolved = scope.resolved_agents()
        assert resolved[0] == "chief", scope.slug
        assert resolved[-1] == "memory", scope.slug


def test_no_scope_lists_an_agent_twice():
    for scope in scopes.SCOPES.values():
        resolved = scope.resolved_agents()
        assert len(resolved) == len(set(resolved)), scope.slug


def test_every_scope_agent_exists_in_the_registry():
    from app.agents import REGISTRY

    for scope in scopes.SCOPES.values():
        for slug in scope.resolved_agents():
            assert slug in REGISTRY, f"{scope.slug} references unknown agent {slug}"


def test_flights_only_is_small():
    scope = scopes.get("flights_only")
    resolved = scope.resolved_agents()
    assert resolved == ("chief", "flight", "memory")
    # The whole point: a fraction of the full roster.
    assert len(resolved) < len(scopes.get("full_trip").resolved_agents()) / 4


def test_dependencies_are_pulled_in():
    """Budget aggregates the itinerary, so asking for budget implies itinerary."""
    scope = scopes.get("budget_check")
    resolved = scope.resolved_agents()
    assert "itinerary" in resolved
    assert resolved.index("itinerary") < resolved.index("budget")


def test_tier3_order_is_preserved_in_every_scope():
    for scope in scopes.SCOPES.values():
        sequential = scope.sequential_agents()
        expected = tuple(s for s in scopes.TIER3_ORDER if s in sequential)
        assert sequential == expected, scope.slug


def test_unknown_scope_falls_back_to_full_trip():
    assert scopes.get("nonsense").slug == "full_trip"
    assert scopes.get(None).slug == "full_trip"


def test_catalogue_is_serialisable():
    entries = scopes.catalogue()
    assert len(entries) == len(scopes.SCOPES)
    for entry in entries:
        assert entry["agent_count"] == len(entry["agents"])
        assert entry["label"] and entry["cta"] and entry["placeholder"]


async def test_scoped_run_invokes_only_its_agents(agent_calls):
    """A flights-only run must not wake the other 18 agents."""
    request = TripRequest(goal="cheap flights from klia to bki on 6 november night")
    results = await supervisor.run_plan(request, TravelerProfile(), scope="flights_only")

    assert set(agent_calls) == {"chief", "flight", "memory"}
    assert sum(agent_calls.values()) == 3
    assert "visa" not in results
    assert "shopping" not in results
    assert results["_scope"]["slug"] == "flights_only"


async def test_scoped_run_still_resolves_the_destination(agent_calls):
    """Scoping must not cost us the Chief's parsing.

    The shared LLM stub resolves every goal to Venice/KUL, so this asserts the
    Chief's values reached the flight agent as IATA codes — not that the words in
    the goal were parsed (which is the stubbed model's job, not ours).
    """
    request = TripRequest(goal="flights klia to bki on 6 november")
    results = await supervisor.run_plan(request, TravelerProfile(), scope="flights_only")

    route = results["flight"]["data"]["route"]
    assert route["origin"] == "KUL"  # stub origin "KUL"
    assert route["destination"] == "VCE"  # stub destination "Venice" → IATA
    assert route["depart"] == "2026-09-01"  # stub start_date reached the agent


async def test_small_scope_skips_the_critic(agent_calls):
    """Scoring a single result against itself is a wasted LLM call."""
    request = TripRequest(goal="hotel in kota kinabalu")
    results = await supervisor.run_plan(request, TravelerProfile(), scope="hotels")
    assert supervisor.CRITIC_NODE not in results


async def test_full_trip_runs_the_critic(agent_calls):
    request = TripRequest(goal="7-day Venice trip for 2")
    results = await supervisor.run_plan(request, TravelerProfile(), scope="full_trip")
    assert supervisor.CRITIC_NODE in results
    assert sum(agent_calls.values()) == supervisor.TOTAL_AGENT_INVOCATIONS


@pytest.mark.parametrize("slug", list(scopes.SCOPES))
async def test_every_scope_runs_without_duplication(slug, agent_calls):
    """No scope may double-invoke an agent — the fan-in barrier rule holds."""
    request = TripRequest(goal="4 days in Kota Kinabalu for 2")
    await supervisor.run_plan(request, TravelerProfile(), scope=slug)

    duplicated = {agent: n for agent, n in agent_calls.items() if n != 1}
    assert not duplicated, f"{slug} duplicated: {duplicated}"
    assert sum(agent_calls.values()) == len(scopes.get(slug).resolved_agents())
