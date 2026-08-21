"""Itinerary dependency-graph re-plan + real-time fare settlement (Tier 4).

Treat the itinerary as a dependency graph: when a leg is disrupted, propagate the
shift through every downstream leg, rebook what breaks (flight via the existing
recovery cascade), and settle the fare difference in real time through the escrow
ledger (real Atlas where a live order exists, ledger otherwise).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agents.memory import MemoryAgent
from app.brain import escrow_store, trip_store
from app.brain.trip_store import reconstruct_request
from app.core.settings import settings
from app.graph import itinerary_graph
from app.graph.disruption import handle_disruption
from app.tools import atlas_sandbox

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/itinerary", tags=["itinerary"])


class ReplanRequest(BaseModel):
    event_type: str = "flight_delayed"  # flight_delayed | flight_cancelled
    delay_minutes: int = 180
    #: Atlas order number if the trip was booked live (enables a real settlement).
    order_no: str | None = None
    persist: bool = True


def _source_node(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The disrupted root — the first flight leg, else the first leg."""
    return next((n for n in nodes if n["kind"] == "flight"), nodes[0] if nodes else None)


def _nodes_to_items(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "day_index": n["day"],
            "kind": n["kind"],
            "title": n["title"],
            "starts_at": n.get("starts_at"),
            "ends_at": n.get("ends_at"),
            "cost_amount": n.get("cost_amount"),
            "cost_currency": n.get("cost_currency"),
        }
        for n in nodes
    ]


@router.get("/graph")
async def get_graph() -> dict[str, Any]:
    results = await trip_store.load_trip_durable() or {}
    return itinerary_graph.build(results)


@router.post("/replan")
async def replan(body: ReplanRequest, request: Request) -> dict[str, Any]:
    """Propagate a disruption through the itinerary graph, rebook the broken
    legs, and settle the fare difference in real time."""
    results = await trip_store.load_trip_durable() or {}
    if not results:
        return {"error": "No active trip to re-plan."}

    graph = itinerary_graph.build(results)
    if not graph["nodes"]:
        return {"error": "The active trip has no itinerary legs to re-plan."}

    source = _source_node(graph["nodes"])
    prop = itinerary_graph.propagate(graph, source["id"], body.delay_minutes)

    # --- Rebook the flight leg via the existing recovery cascade -------------
    original_request = reconstruct_request(results, goal="Dependency-graph re-plan")
    profile = MemoryAgent.load_profile()
    disruption_type = "flight_cancelled" if body.event_type == "flight_cancelled" else "flight_cancelled"
    recovery = await handle_disruption(
        disruption_type=disruption_type,
        affected_agent="flight",
        original_request=original_request,
        profile=profile,
        original_results=results,
    )
    cost = recovery.get("cost_detail") or {}
    fare_delta = cost.get("additional_cost")  # +ve = costs more, -ve = cheaper, None = n/a
    currency = cost.get("currency") or original_request.budget_currency or "MYR"

    # --- Settle the fare difference in real time (escrow) --------------------
    settlement: dict[str, Any] = {"fare_delta": fare_delta, "currency": currency, "direction": "none"}
    if isinstance(fare_delta, (int, float)) and abs(fare_delta) >= 0.01:
        t_ref, t_amount, t_cur = (
            f"{(results.get('flight') or {}).get('data', {}).get('route', {}).get('origin', 'TRIP')}"
            f"-{(results.get('flight') or {}).get('data', {}).get('route', {}).get('destination', '')}",
            0.0,
            currency,
        )
        hold = await escrow_store.open_hold(
            booking_ref=t_ref or "active-trip",
            amount=max(abs(fare_delta), 1.0),
            currency=currency,
            description="Trip fare (re-plan settlement)",
            user_id=(getattr(request.state, "auth", {}) or {}).get("sub"),
        )
        if fare_delta > 0:
            # Costs more → traveller owes the delta. Real charge happens when the
            # replacement is booked via Atlas; record the upcharge now.
            await escrow_store.add_event(
                hold["id"], kind="upcharge", amount=fare_delta, currency=currency, actor="agent",
                reason=f"Fare difference on autonomous re-plan (+{currency} {fare_delta:.2f})",
                settlement="ledger",
            )
            settlement.update({"direction": "upcharge", "mode": "ledger",
                               "note": "Settled on rebooking via Atlas pay.do"})
        else:
            atlas = await atlas_sandbox.refund_raw(
                body.order_no, abs(fare_delta), currency=currency,
                reason="Cheaper alternative found on autonomous re-plan",
            )
            await escrow_store.add_event(
                hold["id"], kind="refund", amount=abs(fare_delta), currency=currency, actor="agent",
                reason="Cheaper alternative found on autonomous re-plan",
                settlement=("atlas-live" if atlas.get("mode") == "live" else "ledger"),
                atlas_ref=atlas.get("atlas_ref"),
            )
            settlement.update({"direction": "refund", "mode": atlas.get("mode")})
        settlement["hold_id"] = hold["id"]

    # --- Persist the shifted itinerary ---------------------------------------
    if body.persist:
        try:
            await trip_store.update_itinerary(_nodes_to_items(prop["nodes"]))
            merged = {**results, **recovery.get("recovery_plan", {})}
            await trip_store.save_trip_durable(merged)
        except Exception as exc:  # noqa: BLE001 — persistence is best-effort
            logger.info("re-plan persist failed: %s", exc)

    return {
        "graph": {"nodes": prop["nodes"], "edges": graph["edges"]},
        "source": source["id"],
        "delay_minutes": body.delay_minutes,
        "impacted": prop["impacted"],
        "rebook": {
            "summary": recovery.get("summary"),
            "additional_cost": recovery.get("additional_cost"),
            "cost_detail": cost,
            "alternatives": [
                {"id": o.get("id"), "title": o.get("title"), "price_amount": o.get("price_amount"),
                 "price_currency": o.get("price_currency"), "bookable": o.get("bookable", False)}
                for o in ((recovery.get("recovery_plan") or {}).get("flight") or {}).get("options", [])[:4]
            ],
        },
        "settlement": settlement,
    }
