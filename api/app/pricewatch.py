"""Price-drop autopilot.

A traveller arms a watch on a fare (baseline price). A background sweep re-prices
each watch through the Flight agent and, when the fare drops past the watch's
threshold, sends one Telegram alert (deduped on ``notified_at``); if the watch is
armed for auto-rebook, it records the cheaper fare and flips to ``rebooked``.

Safety: the sweep never executes a real payment. Like the disruption path, an
"auto-rebook" captures the cheaper bookable fare + notifies — the traveller
confirms the actual booking in-app. A ``simulate`` flag forces a synthetic drop
so the autopilot is demoable deterministically without waiting for a real price
move.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core import db
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/watch", tags=["watch"])

_SIMULATED_DROP = 0.8  # simulate mode returns 80% of baseline → a 20% drop


class CreateWatch(BaseModel):
    origin: str
    destination: str
    depart_date: str | None = None
    travellers: int = 1
    baseline_amount: float
    currency: str = "MYR"
    threshold_pct: int = 10
    auto_rebook: bool = False
    budget_amount: float | None = None


def _user_id(request: Request) -> str | None:
    return (getattr(request.state, "auth", {}) or {}).get("sub")


def _row(r: dict[str, Any]) -> dict[str, Any]:
    def num(v: Any) -> float | None:
        return float(v) if v is not None else None

    return {
        "id": str(r["id"]),
        "origin": r["origin"],
        "destination": r["destination"],
        "depart_date": r["depart_date"],
        "travellers": r["travellers"],
        "baseline_amount": num(r["baseline_amount"]),
        "currency": r["currency"],
        "threshold_pct": r["threshold_pct"],
        "auto_rebook": r["auto_rebook"],
        "budget_amount": num(r["budget_amount"]),
        "last_amount": num(r["last_amount"]),
        "status": r["status"],
        "last_checked_at": r["last_checked_at"].isoformat() if r.get("last_checked_at") else None,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


@router.post("/price")
async def create_watch(body: CreateWatch, request: Request) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    uid = _user_id(request)
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            """INSERT INTO fare_watches
               (user_id, origin, destination, depart_date, travellers, baseline_amount,
                currency, threshold_pct, auto_rebook, budget_amount)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *""",
            uuid.UUID(uid) if uid else None,
            body.origin.strip().upper(),
            body.destination.strip().upper(),
            body.depart_date,
            max(1, body.travellers),
            body.baseline_amount,
            body.currency,
            max(1, min(90, body.threshold_pct)),
            body.auto_rebook,
            body.budget_amount,
        )
    return {"watch": _row(dict(r))}


@router.get("/price")
async def list_watches(request: Request) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"watches": []}
    uid = _user_id(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM fare_watches WHERE (user_id = $1 OR $1 IS NULL) "
            "ORDER BY created_at DESC LIMIT 100",
            uuid.UUID(uid) if uid else None,
        )
    return {"watches": [_row(dict(r)) for r in rows]}


@router.delete("/price/{watch_id}")
async def delete_watch(watch_id: str, request: Request) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    uid = _user_id(request)
    async with pool.acquire() as conn:
        deleted = await conn.execute(
            "DELETE FROM fare_watches WHERE id = $1 AND (user_id = $2 OR $2 IS NULL)",
            uuid.UUID(watch_id),
            uuid.UUID(uid) if uid else None,
        )
    return {"deleted": deleted.endswith("1")}


@router.post("/price/run")
async def run_now(request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the sweep for the caller's watches now (demo-friendly).

    Pass ``{"simulate": true}`` to force a synthetic price drop so the autopilot
    can be demonstrated without waiting for a real fare move.
    """
    simulate = bool((body or {}).get("simulate"))
    return await run_price_watches(user_id=_user_id(request), simulate=simulate)


async def _current_fare(watch: dict[str, Any]) -> dict[str, Any] | None:
    """Re-price a watched route through the Flight agent; cheapest fare or None."""
    from app.agents import REGISTRY
    from app.agents.memory import MemoryAgent
    from app.agents.schemas import TripRequest

    depart: date | None = None
    if watch.get("depart_date"):
        try:
            depart = date.fromisoformat(str(watch["depart_date"])[:10])
        except ValueError:
            depart = None
    try:
        req = TripRequest(
            goal=f"Flights {watch['origin']} to {watch['destination']}"
            + (f" on {watch['depart_date']}" if watch.get("depart_date") else ""),
            origin=watch["origin"],
            destination=watch["destination"],
            start_date=depart,
            travellers=int(watch.get("travellers") or 1),
        )
        profile = MemoryAgent.load_profile()
        res = await REGISTRY["flight"](req, profile)
    except Exception as exc:  # noqa: BLE001 — re-pricing is best-effort
        logger.info("price re-quote failed for %s→%s: %s", watch["origin"], watch["destination"], exc)
        return None

    options = [o.model_dump(mode="json") if hasattr(o, "model_dump") else o for o in (res.options or [])]
    priced = []
    for o in options:
        try:
            amt = float(o.get("price_amount")) if o.get("price_amount") is not None else None
        except (TypeError, ValueError):
            amt = None
        if amt and amt > 0:
            priced.append((amt, o))
    if not priced:
        return None
    priced.sort(key=lambda p: p[0])
    amt, o = priced[0]
    return {
        "amount": amt,
        "currency": o.get("price_currency") or "MYR",
        "bookable": bool(o.get("bookable")),
        "booking_url": o.get("booking_url"),
        "title": o.get("title"),
    }


async def run_price_watches(*, user_id: str | None = None, simulate: bool = False) -> dict[str, Any]:
    """Re-price active watches; alert (and optionally auto-rebook) on a drop.

    ``user_id`` scopes an on-demand run to one traveller; the periodic task
    passes None to sweep everyone. Each triggered watch alerts once.
    """
    from app.tools import notify

    pool = await db.get_pool()
    if pool is None:
        return {"checked": 0, "triggered": []}

    clause = "status = 'active'"
    args: list[Any] = []
    if user_id:
        args.append(uuid.UUID(user_id))
        clause += f" AND user_id = ${len(args)}"
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"SELECT * FROM fare_watches WHERE {clause} ORDER BY created_at LIMIT 100", *args)

    checked = 0
    triggered: list[dict[str, Any]] = []
    for r in rows:
        w = dict(r)
        baseline = float(w["baseline_amount"])
        checked += 1

        if simulate:
            current = {"amount": round(baseline * _SIMULATED_DROP, 2), "currency": w["currency"],
                       "bookable": True, "booking_url": None, "title": "Simulated cheaper fare"}
        else:
            current = await _current_fare(w)

        if not current:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE fare_watches SET last_checked_at = now() WHERE id = $1", w["id"])
            continue

        cur_amt = float(current["amount"])
        target = baseline * (1 - int(w["threshold_pct"]) / 100)
        dropped = cur_amt <= target

        if not dropped:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE fare_watches SET last_amount = $2, last_checked_at = now() WHERE id = $1",
                    w["id"], cur_amt,
                )
            continue

        drop_pct = round((baseline - cur_amt) / baseline * 100) if baseline else 0
        cur = current["currency"] or w["currency"]
        within_budget = w["budget_amount"] is None or cur_amt <= float(w["budget_amount"])
        will_rebook = bool(w["auto_rebook"]) and current["bookable"] and within_budget
        new_status = "rebooked" if will_rebook else "triggered"

        text = (
            f"📉 <b>Fare drop</b> {w['origin']}→{w['destination']}"
            + (f" on {w['depart_date']}" if w.get("depart_date") else "")
            + f"\nNow <b>{cur} {cur_amt:,.0f}</b> (was {cur} {baseline:,.0f}, −{drop_pct}%)."
        )
        if will_rebook:
            text += "\n✅ Auto-rebook armed — captured the cheaper fare; confirm in the app."
        elif current.get("booking_url"):
            text += f"\nBook it: {current['booking_url']}"
        try:
            await notify.broadcast(text)
        except Exception as exc:  # noqa: BLE001
            logger.info("price-drop notify failed: %s", exc)

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE fare_watches SET last_amount = $2, status = $3, "
                "last_checked_at = now(), notified_at = now() WHERE id = $1",
                w["id"], cur_amt, new_status,
            )
        triggered.append({
            "id": str(w["id"]),
            "route": f"{w['origin']}→{w['destination']}",
            "was": baseline, "now": cur_amt, "drop_pct": drop_pct,
            "currency": cur, "status": new_status, "within_budget": within_budget,
        })

    return {"checked": checked, "triggered": triggered, "simulated": simulate}
