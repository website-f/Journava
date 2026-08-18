"""Brain graph and memory behaviour (spec §7).

The graph used to be built only from domains that happened to hold data, so a
fresh install rendered two nodes and no edges while a hard-coded eight-node
"demo graph" sat unused in main.py. Node weights are the live memory counts now,
which is what makes the "brain growing" demo real rather than staged.
"""

from __future__ import annotations

import json

import pytest

from app.agents.memory import MemoryAgent
from app.agents.schemas import TravelerProfile, TripRequest
from app.brain import gnosion_client

pytestmark = pytest.mark.usefixtures("memory_brain")


def test_graph_declares_every_known_domain():
    graph = gnosion_client.graph()
    assert {node["id"] for node in graph["nodes"]} == set(gnosion_client.KNOWN_DOMAINS)
    assert len(graph["edges"]) == len(gnosion_client.DOMAIN_EDGES)


def test_graph_edges_only_reference_real_nodes():
    graph = gnosion_client.graph()
    node_ids = {node["id"] for node in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


def test_graph_reports_its_backend_honestly():
    """A fallback store must never be presented as Gnosion."""
    graph = gnosion_client.graph()
    assert graph["backend"] == "in-process-fallback"
    assert gnosion_client.available() is False
    assert gnosion_client.snapshot()["backend"] == "in-process-fallback"


def test_weights_climb_as_memories_are_written():
    before = gnosion_client.graph()["total_memories"]

    gnosion_client.remember("flights", "venice", json.dumps({"opt": 1}))
    gnosion_client.remember("hotels", "venice", json.dumps({"opt": 2}))

    after = gnosion_client.graph()
    assert after["total_memories"] == before + 2

    weights = {node["id"]: node["weight"] for node in after["nodes"]}
    assert weights["flights"] == 1
    assert weights["hotels"] == 1


def test_seed_profile_keys_match_the_model():
    """The seed must survive validation with its preferences intact.

    A hand-written seed used `dietary: "halal"` and `no_red_eye: true`, neither of
    which are `TravelerProfile` fields. Pydantic ignores unknown keys, so the
    profile validated cleanly with halal silently switched off — and every halal
    scoping rule downstream quietly stopped applying.
    """
    profile = MemoryAgent.load_profile()
    assert profile.halal_required is True
    assert profile.avoid_red_eye is True
    assert profile.home_airport == "KUL"
    assert profile.max_connections == 1
    assert "food" in profile.interests


def test_unreadable_profile_falls_back_to_global_search():
    gnosion_client.remember("traveler_profile", "current", "not json at all")
    profile = MemoryAgent.load_profile()
    # An empty profile means "search globally" (§7.5), not a crash.
    assert profile.halal_required is False
    assert profile.interests == []


def test_outcomes_are_recorded_for_preference_learning():
    MemoryAgent.record_outcome("flight", {"title": "Qatar 1 stop"}, True)
    MemoryAgent.record_outcome("flight", {"title": "Red-eye 3 stops"}, False)

    weights = {n["id"]: n["weight"] for n in gnosion_client.graph()["nodes"]}
    assert weights["decision_outcomes"] == 2

    stats = gnosion_client.graph()["outcomes"]
    assert stats["flight"] == {"accepted": 1, "rejected": 1}


async def test_memory_agent_captures_the_run():
    """Every upstream agent that produced something leaves a memory behind."""
    agent = MemoryAgent()
    context = {
        "chief": {"data": {"destination": "Venice"}},
        "flight": {"summary": "3 options", "options": [{"title": "QR"}]},
        "hotel": {"summary": "2 options", "options": [{"title": "Canal View"}]},
        "research": {
            "summary": "5 attractions",
            "options": [{"kind": "restaurant", "title": "Orient", "halal_confidence": "certified"}],
        },
        "itinerary": {"summary": "14 items", "options": []},
    }
    result = await agent.run(
        TripRequest(goal="g", destination="Venice"), TravelerProfile(), context=context
    )

    assert result.data["memories_written"] >= 4
    weights = {n["id"]: n["weight"] for n in gnosion_client.graph()["nodes"]}
    assert weights["destinations"] == 1
    assert weights["dining"] == 1


async def test_profile_is_not_rewritten_when_unchanged():
    """Repeat runs must not pile up identical profile entries."""
    agent = MemoryAgent()
    profile = MemoryAgent.load_profile()

    for _ in range(3):
        await agent.run(TripRequest(goal="g"), profile, context={})

    weights = {n["id"]: n["weight"] for n in gnosion_client.graph()["nodes"]}
    assert weights["traveler_profile"] == 1
