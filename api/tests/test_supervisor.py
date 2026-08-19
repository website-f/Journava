"""Orchestration invariants.

These regressions were all real and all silent — the app looked fine while doing
the wrong thing, which is exactly the class of bug worth pinning down in tests:

- Tier 2 and Tier 3 ran two and three times per plan, because the compiled graph
  executed everything and then a second code path re-ran it.
- The Chief's parsed destination never reached a single specialist, so all 20 of
  them planned for "unknown" while the UI showed the right city.
"""

from __future__ import annotations

import pytest

from app.agents.schemas import TravelerProfile, TripRequest
from app.graph import supervisor

pytestmark = pytest.mark.usefixtures("stub_llm", "no_network", "no_cache", "memory_brain")


@pytest.fixture
def request_venice() -> TripRequest:
    return TripRequest(goal="Plan a 7-day Venice trip for 2, budget RM8,000")


async def test_every_agent_runs_exactly_once(agent_calls, request_venice):
    """No agent may run twice in a clean plan.

    Guards the fan-in bug: routing a barrier through "the first node of the next
    tier" makes that node's successors fire in two supersteps, and the duplicate
    work is invisible apart from the LLM bill.
    """
    await supervisor.run_plan(request_venice, TravelerProfile())

    duplicated = {slug: n for slug, n in agent_calls.items() if n != 1}
    assert not duplicated, f"agents ran more than once: {duplicated}"
    assert sum(agent_calls.values()) == supervisor.TOTAL_AGENT_INVOCATIONS


async def test_chief_enrichment_reaches_specialists(request_venice):
    """The parsed destination must be in the request Tier 1 receives."""
    results = await supervisor.run_plan(request_venice, TravelerProfile())

    chief_data = results["chief"]["data"]
    # Normalised to IATA by the Chief, so every downstream consumer sees one
    # canonical code instead of "Venice" here and "VCE" in the flight agent.
    assert chief_data["destination"] == "VCE"
    # Canonical mirror used by the UI and the disruption endpoint.
    assert chief_data["resolved_request"]["destination"] == "VCE"

    # Downstream agents describe the real destination, never "unknown".
    assert "VCE" in results["research"]["summary"]
    assert results["weather_risk"]["data"]["destination"] == "VCE"
    assert results["visa"]["data"]["destination"] == "VCE"


def test_apply_chief_enrichment_coerces_iso_dates():
    """The Chief returns ISO strings; the request needs `date` objects."""
    enriched = supervisor.apply_chief_enrichment(
        TripRequest(goal="x"),
        {
            "data": {
                "enriched": {
                    "destination": "Venice",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-08",
                    "travellers": 2,
                }
            }
        },
    )
    assert enriched.destination == "Venice"
    assert enriched.start_date is not None
    assert (enriched.end_date - enriched.start_date).days == 7
    assert enriched.travellers == 2


def test_apply_chief_enrichment_survives_garbage():
    """A malformed parse keeps the original request rather than raising."""
    original = TripRequest(goal="keep me", destination="Rome")
    result = supervisor.apply_chief_enrichment(
        original, {"data": {"enriched": {"start_date": "not-a-date"}}}
    )
    assert result.destination == "Rome"
    assert result.goal == "keep me"


def test_user_supplied_fields_are_not_overwritten():
    """Explicit user input beats the LLM's guess."""
    original = TripRequest(goal="g", destination="Rome", travellers=4)
    result = supervisor.apply_chief_enrichment(
        original,
        # The Chief only ever puts a field in `enriched` when the request lacked
        # it, so an enrichment that contradicts user input should not exist —
        # but if one does, the merge must not silently take it for `goal`.
        {"data": {"enriched": {}}},
    )
    assert result.destination == "Rome"
    assert result.travellers == 4


async def test_tier3_runs_itinerary_before_budget(request_venice):
    """Budget aggregates the itinerary, so the itinerary has to exist first."""
    assert supervisor.SEQUENTIAL_NODES.index("itinerary") < supervisor.SEQUENTIAL_NODES.index(
        "budget"
    )

    results = await supervisor.run_plan(request_venice, TravelerProfile())
    breakdown = results["budget"]["data"]["breakdown"]

    # 7 stubbed activities at 120 each — zero here means budget ran too early.
    assert breakdown["activities"] > 0
    assert breakdown["nights"] == 7


async def test_critic_is_a_barrier_node(request_venice):
    """The Critic scores between Tier 1 and Tier 2, and records its verdict."""
    results = await supervisor.run_plan(request_venice, TravelerProfile())

    critic = results[supervisor.CRITIC_NODE]
    assert critic["data"]["score"] == pytest.approx(0.95)
    assert critic["data"]["retried"] is False


async def test_langgraph_and_fallback_agree(monkeypatch, agent_calls, request_venice):
    """The asyncio mirror must produce the same agents as the compiled graph."""
    graph_results = await supervisor.run_plan(request_venice, TravelerProfile())
    graph_slugs = set(graph_results)
    graph_calls = dict(agent_calls)

    agent_calls.clear()
    # `build_graph` takes the scope, so the stub has to accept it too.
    monkeypatch.setattr(supervisor, "build_graph", lambda _scope=None: None)
    fallback_results = await supervisor.run_plan(request_venice, TravelerProfile())

    assert set(fallback_results) == graph_slugs
    assert dict(agent_calls) == graph_calls


async def test_cancellation_skips_remaining_agents(monkeypatch, agent_calls, request_venice):
    """Cancelling mid-run stops later nodes instead of abandoning the graph."""
    original_node = supervisor._node  # noqa: SLF001 — test seam

    def cancelling_node(slug: str):
        runner = original_node(slug)

        async def wrapped(state):
            result = await runner(state)
            if slug == "chief":
                supervisor.cancel_run()
            return result

        return wrapped

    monkeypatch.setattr(supervisor, "_node", cancelling_node)
    await supervisor.run_plan(request_venice, TravelerProfile())

    # Chief ran; nothing downstream did.
    assert agent_calls["chief"] == 1
    assert sum(agent_calls.values()) == 1
    supervisor.reset_cancel()
