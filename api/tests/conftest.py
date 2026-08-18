"""Shared fixtures.

Every test here runs fully offline: the LLM gateway, the HTTP tools and the
brain are all stubbed. That is deliberate — these tests assert *orchestration*
invariants (how many times an agent runs, whether the parsed destination reaches
it, which direction money converts), and a real network would make them slow and
flaky without testing any of that better.
"""

from __future__ import annotations

import collections
import json
from typing import Any

import pytest


@pytest.fixture
def stub_llm(monkeypatch: pytest.MonkeyPatch):
    """Replace every LLM entry point with a deterministic JSON responder.

    Agents import `complete` in two styles (`from app.core import llm` then
    `llm.complete`, and `from app.core.llm import complete`), so the module
    attribute has to be patched everywhere it was bound.
    """
    calls: list[dict[str, Any]] = []

    payload = {
        "destination": "Venice",
        "origin": "KUL",
        "start_date": "2026-09-01",
        "end_date": "2026-09-08",
        "travellers": 2,
        "budget_amount": 8000,
        "budget_currency": "MYR",
        "interests_detected": ["food", "culture"],
        # Critic
        "score": 0.95,
        "weakest_agent": None,
        "critique": "",
        # Flight / hotel
        "options": [
            {
                "id": "F1",
                "title": "Qatar Airways — 1 stop",
                "price_amount": 2400,
                "price_currency": "MYR",
                "reasoning": "Best value",
                "raw": {"stops": 1, "duration_hours": 16, "baggage_included": True},
            }
        ],
        # Itinerary
        "items": [
            {
                "day_index": day,
                "kind": "activity",
                "title": f"Day {day} in Venice",
                "cost_amount": 120,
                "cost_currency": "MYR",
            }
            for day in range(1, 8)
        ],
        # Research
        "attractions": [
            {"title": "St Mark's Basilica", "reasoning": "Iconic", "estimated_cost": 30}
        ],
        "dining": [
            {
                "title": "Orient Experience",
                "cuisine": "Middle Eastern",
                "halal_confidence": "certified",
                "reasoning": "Popular with Muslim travellers",
                "estimated_cost": 45,
            }
        ],
        "contradictions_detected": [],
    }

    async def fake_complete(messages, **kwargs):
        calls.append({"messages": messages, "kwargs": kwargs})
        return json.dumps(payload)

    import app.core.llm as llm_module

    monkeypatch.setattr(llm_module, "complete", fake_complete)

    # Rebind in every module that imported the symbol directly.
    from app.agents import chief, flight, hotel, itinerary, research

    for module in (chief, flight, hotel, itinerary, research):
        if hasattr(module, "complete"):
            monkeypatch.setattr(module, "complete", fake_complete)

    fake_complete.calls = calls  # type: ignore[attr-defined]
    return fake_complete


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch):
    """Neutralise every external tool so nothing reaches the internet."""
    from app.tools import (
        amadeus,
        atlas_skill,
        camofox,
        frankfurter,
        gdelt,
        halal,
        open_meteo,
        reddit,
        rest_countries,
        youtube,
    )

    async def none(*_args, **_kwargs):
        return None

    async def empty_list(*_args, **_kwargs):
        return []

    async def false(*_args, **_kwargs):
        return False

    async def empty_dict(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(camofox, "available", false)
    monkeypatch.setattr(camofox, "search", none)
    monkeypatch.setattr(youtube, "search_videos", none)
    monkeypatch.setattr(youtube, "video_stats", none)
    monkeypatch.setattr(reddit, "search", none)
    monkeypatch.setattr(gdelt, "events", empty_list)
    monkeypatch.setattr(gdelt, "threat_keywords", empty_list)
    monkeypatch.setattr(gdelt, "tone_analysis", empty_dict)
    monkeypatch.setattr(rest_countries, "country_info", none)
    monkeypatch.setattr(frankfurter, "rates", none)
    monkeypatch.setattr(amadeus, "search_flights", none)
    monkeypatch.setattr(open_meteo, "geocode", none)
    monkeypatch.setattr(open_meteo, "forecast", none)

    # The budget agent binds `rates` at import time.
    from app.agents import budget as budget_agent

    monkeypatch.setattr(budget_agent, "fx_rates", none)

    # Open-Meteo is imported by name into the weather agent.
    from app.agents import weather_risk

    monkeypatch.setattr(weather_risk, "geocode", none)
    monkeypatch.setattr(weather_risk, "forecast", none)

    # Atlas: every entry point raises, standing in for "CLI not installed".
    async def atlas_unavailable(*_args, **_kwargs):
        raise atlas_skill.AtlasSkillError("stubbed offline")

    for name in (
        "search",
        "verify_offer",
        "confirm_price",
        "create_order",
        "pay_order",
        "order_status",
        "list_baggage",
        "list_seats",
        "doctor",
        "use_environment",
        "auth_login",
        "auth_poll",
        "auth_status",
    ):
        monkeypatch.setattr(atlas_skill, name, atlas_unavailable)

    async def atlas_absent(*_args, **_kwargs):
        return False

    monkeypatch.setattr(atlas_skill, "available", atlas_absent)

    # Camofox's source-aware search shares the same stub as the plain one.
    monkeypatch.setattr(camofox, "search_with_sources", none)

    # The vault must not reach Postgres during unit tests.
    from app.core import vault

    async def no_credential(*_args, **_kwargs):
        return None

    monkeypatch.setattr(vault, "resolve", no_credential)
    monkeypatch.setattr(vault, "secret_for", no_credential)

    async def unverified_batch(restaurants):
        return [
            {"confidence": "unverified", "source": None, "cert_body": None, "notes": "offline stub"}
            for _ in restaurants
        ]

    monkeypatch.setattr(halal, "verify_batch", unverified_batch)


@pytest.fixture
def no_cache(monkeypatch: pytest.MonkeyPatch):
    """Bypass Redis so `cached()` always calls its producer."""
    from app.core import cache

    async def passthrough(_key, producer, **_kwargs):
        return await producer()

    monkeypatch.setattr(cache, "cached", passthrough)
    for module_name in ("app.agents.flight", "app.agents.hotel"):
        import importlib

        module = importlib.import_module(module_name)
        if hasattr(module, "cached"):
            monkeypatch.setattr(module, "cached", passthrough)


@pytest.fixture
def agent_calls(monkeypatch: pytest.MonkeyPatch) -> collections.Counter:
    """Count how many times each agent is invoked during a run."""
    import app.agents.base as base

    counter: collections.Counter = collections.Counter()
    original = base.BaseAgent.__call__

    async def counting(self, request, profile, **kwargs):
        counter[self.slug] += 1
        return await original(self, request, profile, **kwargs)

    monkeypatch.setattr(base.BaseAgent, "__call__", counting)
    return counter


@pytest.fixture
def memory_brain(monkeypatch: pytest.MonkeyPatch):
    """Isolate the brain: an empty in-process store per test."""
    from app.brain import gnosion_client

    fresh = gnosion_client._InProcessFallback()  # noqa: SLF001 — test seam
    monkeypatch.setattr(gnosion_client, "_fallback", fresh)
    monkeypatch.setattr(gnosion_client, "_brain", None)
    monkeypatch.setattr(gnosion_client, "_brain_loaded", True)  # force fallback
    return fresh
