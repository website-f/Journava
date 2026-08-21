"""Escrow + AI-adjudicated settlement API (the ×2 multiplier surface).

Open a hold on booking; when a claim comes in, an agent decides the refund/
release split and the settlement executes autonomously: the refund is attempted
for real against Atlas and recorded either way, the remainder is released to the
supplier — all as immutable ledger events.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.brain import escrow_store, trip_store
from app.core.settings import settings
from app.tools import adjudicator, atlas_sandbox

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/escrow", tags=["escrow"])


class OpenHoldRequest(BaseModel):
    booking_ref: str | None = None
    amount: float | None = None
    currency: str = "MYR"
    description: str = ""
    #: If true and no amount given, seed the hold from the active trip's flight.
    from_active_trip: bool = False


class AdjudicateRequest(BaseModel):
    hold_id: str | None = None
    booking_ref: str | None = None
    event_type: str = "flight_delayed"  # flight_delayed | flight_cancelled | downgrade | no_show | service_issue
    delay_minutes: int | None = None
    evidence: str = ""
    #: Atlas order number, if this booking was paid via Atlas (enables a real refund attempt).
    order_no: str | None = None


def _trip_flight_amount(results: dict[str, Any]) -> tuple[str, float, str]:
    """Booking ref + cheapest flight fare + currency from the active trip."""
    flight = (results or {}).get("flight") or {}
    options = flight.get("options") or []
    priced = [o for o in options if o.get("price_amount") is not None]
    cheapest = min(priced, key=lambda o: float(o["price_amount"]), default=None)
    route = (flight.get("data") or {}).get("route") or {}
    ref = f"{route.get('origin', 'TRIP')}-{route.get('destination', '')}-{route.get('depart', '')}".strip("-")
    amount = float(cheapest["price_amount"]) if cheapest else 0.0
    currency = (cheapest or {}).get("price_currency") or "MYR"
    return (ref or "active-trip"), amount, currency


@router.post("/hold")
async def open_hold(body: OpenHoldRequest, request: Request) -> dict[str, Any]:
    claims = getattr(request.state, "auth", {}) or {}
    user_id = claims.get("sub")
    ref, amount, currency = body.booking_ref or "", body.amount or 0.0, body.currency
    if body.from_active_trip or (not amount):
        results = await trip_store.load_trip_durable() or {}
        t_ref, t_amount, t_cur = _trip_flight_amount(results)
        ref = ref or t_ref
        amount = amount or t_amount
        currency = currency if body.amount else t_cur
    if amount <= 0:
        return {"error": "Nothing to hold — no amount and no active-trip fare found."}
    hold = await escrow_store.open_hold(
        booking_ref=ref,
        amount=amount,
        currency=currency,
        description=body.description or f"Flight booking {ref}",
        user_id=user_id,
    )
    return {"hold": hold}


@router.get("/holds")
async def list_holds(limit: int = 25) -> dict[str, Any]:
    return {"holds": await escrow_store.list_holds(limit=limit)}


@router.get("/holds/{hold_id}")
async def get_hold(hold_id: str) -> dict[str, Any]:
    hold = await escrow_store.get_hold(hold_id)
    return {"hold": hold} if hold else {"error": "not found"}


@router.post("/adjudicate")
async def adjudicate(body: AdjudicateRequest, request: Request) -> dict[str, Any]:
    """Agent decides the split, then the settlement executes autonomously."""
    hold = None
    if body.hold_id:
        hold = await escrow_store.get_hold(body.hold_id)
    elif body.booking_ref:
        holds = await escrow_store.list_holds(limit=100)
        hold = next((h for h in holds if h["booking_ref"] == body.booking_ref), None)
    if not hold:
        return {"error": "No escrow hold found — open one first."}

    claim = {
        "event_type": body.event_type,
        "delay_minutes": body.delay_minutes,
        "evidence": body.evidence,
        "description": hold.get("description"),
    }
    decision = await adjudicator.adjudicate(hold, claim)

    settlement = {"refund": None, "release": None}
    # --- Refund leg: attempt a real Atlas refund, record either way ---
    if decision["refund_amount"] > 0:
        atlas = await atlas_sandbox.refund_raw(
            body.order_no,
            decision["refund_amount"],
            currency=decision["currency"],
            reason=f"{body.event_type}: {decision['rationale'][:120]}",
        )
        await escrow_store.add_event(
            hold["id"],
            kind="refund",
            amount=decision["refund_amount"],
            currency=decision["currency"],
            actor="agent",
            reason=decision["rationale"],
            settlement=("atlas-live" if atlas.get("mode") == "live" else "ledger"),
            atlas_ref=atlas.get("atlas_ref"),
            meta={"policy_basis": decision["policy_basis"], "refund_pct": decision["refund_pct"]},
        )
        settlement["refund"] = atlas
        # Post the refund to the finance ledger so it shows on the Finance page.
        try:
            from app.auth.deps import resolve_org_id
            from app.finance import record as finance_record

            await finance_record(
                org_id=await resolve_org_id(request),
                kind="refund",
                amount=decision["refund_amount"],
                currency=decision["currency"],
                reference=hold.get("booking_ref"),
                counterparty="traveller",
                description=f"AI-adjudicated refund ({decision['refund_pct']}%) — {body.event_type}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("finance record (refund) skipped: %s", exc)
    # --- Release leg: remainder to the supplier ---
    if decision["release_amount"] > 0:
        await escrow_store.add_event(
            hold["id"],
            kind="release",
            amount=decision["release_amount"],
            currency=decision["currency"],
            actor="agent",
            reason="Released to supplier after adjudication",
            settlement="ledger",
        )
        settlement["release"] = {"amount": decision["release_amount"], "currency": decision["currency"]}

    return {
        "decision": decision,
        "settlement": settlement,
        "hold": await escrow_store.get_hold(hold["id"]),
    }
