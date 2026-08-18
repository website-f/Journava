"""HTTP surface smoke tests.

Covers the endpoints the frontend depends on, including the ones added while
wiring the outcome flywheel. `lifespan` is skipped: it touches Postgres, Redis
and seeds a demo trip, none of which these assertions need.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.usefixtures("memory_brain")


@pytest.fixture
def client() -> TestClient:
    # No `with` block — entering the context would run lifespan.
    return TestClient(app)


def test_health_reports_the_memory_backend(client: TestClient):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["agents"] == 21
    # Naming the backend is what keeps a fallback from masquerading as the brain.
    assert body["memory_backend"] in {"gnosion", "in-process-fallback"}
    assert set(body["dependencies"]) == {"postgres", "redis", "gnosion", "camofox"}


def test_agent_roster_matches_the_registry(client: TestClient):
    from app.agents import REGISTRY

    roster = client.get("/api/v1/agents").json()
    assert {a["slug"] for a in roster} == set(REGISTRY)
    assert all(a["name"] and a["role"] for a in roster)


def test_brain_graph_shape(client: TestClient):
    graph = client.get("/api/v1/brain/graph").json()
    assert graph["nodes"] and graph["edges"]
    node = graph["nodes"][0]
    assert {"id", "label", "domain", "weight"} <= set(node)
    assert "backend" in graph


def test_brain_snapshot(client: TestClient):
    snapshot = client.get("/api/v1/brain/snapshot").json()
    assert "backend" in snapshot
    assert "domains" in snapshot


def test_profile_round_trip(client: TestClient):
    payload = {
        "halal_required": True,
        "interests": ["food"],
        "home_airport": "KUL",
        "max_connections": 1,
        "avoid_red_eye": True,
    }
    saved = client.post("/api/v1/profile", json=payload).json()
    assert saved["halal_required"] is True

    loaded = client.get("/api/v1/profile").json()
    assert loaded["halal_required"] is True
    assert loaded["home_airport"] == "KUL"


def test_record_outcome(client: TestClient):
    response = client.post(
        "/api/v1/outcome",
        json={
            "domain": "flight",
            "recommendation": {"id": "F1", "title": "Qatar 1 stop"},
            "accepted": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recorded"] is True
    assert body["accepted"] is True

    # It reached the brain, which is the point of the endpoint.
    from app.brain import gnosion_client

    weights = {n["id"]: n["weight"] for n in gnosion_client.graph()["nodes"]}
    assert weights["decision_outcomes"] == 1


def test_outcome_stats_without_a_database(client: TestClient):
    """No Postgres means an empty list, not a 500."""
    assert client.get("/api/v1/outcome/stats").json() == []


def test_trip_is_absent_before_planning(client: TestClient):
    assert client.get("/api/v1/trip").json() == {"trip": None}


def test_cancel_is_idempotent(client: TestClient):
    from app.graph import supervisor

    assert client.post("/api/v1/cancel").json() == {"cancelled": True}
    assert supervisor.is_cancelled() is True
    supervisor.reset_cancel()


def test_unknown_provider_returns_404(client: TestClient):
    """Engine CRUD must 404 rather than 500 when Postgres is absent."""
    response = client.delete("/api/v1/engine/providers/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
