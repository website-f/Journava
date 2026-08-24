"""Autonomous flight monitoring + budget-aware auto-reschedule.

Detects a delay/cancellation on the active trip's flight (real crawl-first,
labelled sim fallback) and, when disrupted, runs the existing recovery cascade to
rebuild the trip — then flags which alternatives fall inside the traveller's
budget and pings the connected Telegram bots. `simulate` drives the demo.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agents.memory import MemoryAgent
from app.brain import trip_store
from app.brain.trip_store import reconstruct_request
from app.core.settings import settings
from app.graph.disruption import handle_disruption
from app.tools import flight_status, notify, telegram

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/monitor", tags=["monitor"])


@router.get("/health")
async def health() -> dict[str, Any]:
    """Golden-signal snapshot for ops + the Mission Control health strip:
    per-agent calls/errors/latency (24h), cache hit-rate, and roll-up totals."""
    from app.core import cache
    from app.core.llm_providers import get_agent_stats

    agents = await get_agent_stats()
    calls = sum(int(a["calls"]) for a in agents)
    errors = sum(int(a["errors"]) for a in agents)
    tokens = sum(int(a["tokens"]) for a in agents)
    slowest = max(agents, key=lambda a: (a.get("p95_ms") or 0), default=None)
    return {
        "agents": agents,
        "cache": cache.cache_stats(),
        "totals": {
            "llm_calls_24h": calls,
            "errors_24h": errors,
            "error_rate": round(errors / calls, 3) if calls else 0,
            "tokens_24h": tokens,
            "slowest_agent": slowest["agent"] if slowest else None,
        },
    }


class WatchRequest(BaseModel):
    #: Force a disruption for the demo ("money shot"); None = real detection.
    simulate: Literal["delayed", "cancelled", "on_time"] | None = None
    #: A delay at/above this many minutes counts as a disruption.
    threshold_minutes: int = 90
    #: When disrupted, persist the rebuilt trip (True) or only suggest (False).
    auto_reschedule: bool = True


def _selected_flight(results: dict[str, Any]) -> dict[str, Any]:
    """Pull carrier + route from the active trip's flight result."""
    flight = results.get("flight") or {}
    data = flight.get("data") or {}
    route = data.get("route") or {}
    options = flight.get("options") or []
    # Prefer the ranked best-value option, else the first.
    best_id = (data.get("ranking") or {}).get("best_value")
    chosen = next((o for o in options if o.get("id") == best_id), options[0] if options else {})
    raw = chosen.get("raw") or {}
    carrier = raw.get("airline") or (chosen.get("title") or "").split("·")[0].strip()
    return {
        "carrier": carrier,
        "origin": route.get("origin", ""),
        "destination": route.get("destination", ""),
        "depart": route.get("depart", ""),
        "title": chosen.get("title", ""),
    }


def _annotate_budget(options: list[dict[str, Any]], amount: float | None, currency: str) -> dict[str, Any]:
    """Tag each alternative in/out of budget and summarise."""
    annotated: list[dict[str, Any]] = []
    within = 0
    cheapest_within: float | None = None
    for o in options[:6]:
        price = o.get("price_amount")
        in_budget = None
        if amount and price is not None:
            in_budget = float(price) <= float(amount)
            if in_budget:
                within += 1
                cheapest_within = price if cheapest_within is None else min(cheapest_within, price)
        annotated.append(
            {
                "id": o.get("id"),
                "title": o.get("title"),
                "price_amount": price,
                "price_currency": o.get("price_currency"),
                "bookable": o.get("bookable", False),
                "booking_url": o.get("booking_url"),
                "within_budget": in_budget,
            }
        )
    return {
        "alternatives": annotated,
        "budget": {
            "amount": amount,
            "currency": currency,
            "within_budget_count": within,
            "total_alternatives": len(annotated),
            "cheapest_within": cheapest_within,
        },
    }


@router.post("/flight")
async def watch_flight(body: WatchRequest, request: Request) -> dict[str, Any]:
    """Check the active trip's flight; auto-reschedule within budget if disrupted."""
    results = await trip_store.load_trip_durable() or {}
    if not results.get("flight"):
        return {"disrupted": False, "status": None, "reason": "No active trip with a flight to watch."}

    sel = _selected_flight(results)
    status = await flight_status.check_status(
        carrier=sel["carrier"],
        origin=sel["origin"],
        destination=sel["destination"],
        date=sel["depart"],
        force=body.simulate,
    )

    disrupted = status["status"] == "cancelled" or (
        status["status"] == "delayed"
        and (status["delay_minutes"] is None or status["delay_minutes"] >= body.threshold_minutes)
    )

    if not disrupted:
        return {
            "disrupted": False,
            "status": status,
            "flight": sel,
            "threshold_minutes": body.threshold_minutes,
        }

    # --- Disrupted: rebuild the trip and bound alternatives to budget ---
    original_request = reconstruct_request(results, goal="Recovery from flight disruption")
    profile = MemoryAgent.load_profile()
    recovery = await handle_disruption(
        disruption_type="flight_cancelled",
        affected_agent="flight",
        original_request=original_request,
        profile=profile,
        original_results=results,
    )

    new_flight = (recovery.get("recovery_plan") or {}).get("flight") or {}
    budget = _annotate_budget(
        new_flight.get("options") or [],
        (float(original_request.budget_amount) if original_request.budget_amount else None),
        original_request.budget_currency or profile.budget_currency or "MYR",
    )

    if body.auto_reschedule:
        await trip_store.save_trip_durable({**results, **recovery.get("recovery_plan", {})})

    notified = False
    try:
        b = budget["budget"]
        within = b["within_budget_count"]
        cur = b["currency"]
        line = (
            f"✈️ Journava: your flight {sel['carrier']} {sel['origin']}→{sel['destination']} "
            f"is {status['status'].upper()}"
            + (f" (~{status['delay_minutes']} min)" if status.get("delay_minutes") else "")
            + f". {recovery['summary']}. "
            + (f"{within} alternative(s) within your {cur} budget." if b["amount"] else f"{b['total_alternatives']} alternatives found.")
        )
        _res = await notify.broadcast(line)
        notified = any(_res.values())
    except Exception as exc:  # noqa: BLE001 — notify is best-effort
        logger.info("disruption notify failed: %s", exc)

    return {
        "disrupted": True,
        "status": status,
        "flight": sel,
        "threshold_minutes": body.threshold_minutes,
        "auto_rescheduled": body.auto_reschedule,
        "recovery": {
            "summary": recovery["summary"],
            "additional_cost": recovery["additional_cost"],
            "cost_detail": recovery["cost_detail"],
            "agents_activated": recovery["agents_activated"],
        },
        "notified": notified,
        **budget,
    }
