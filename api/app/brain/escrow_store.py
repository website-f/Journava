"""Escrow ledger persistence (the AI-multiplier's money layer).

A hold is opened when a trip is booked; the AI adjudicator later releases it to
the supplier and/or refunds the traveller, appending an immutable event for every
movement. Postgres-backed with an in-process fallback so the demo still runs
without a database.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core import db

logger = logging.getLogger("journava")

#: In-process fallback store (tier 2) — {hold_id: {**hold, "events": [...]}}.
_MEM: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _remaining(hold: dict[str, Any]) -> float:
    return round(float(hold["amount"]) - float(hold["released"]) - float(hold["refunded"]), 2)


async def open_hold(
    *,
    booking_ref: str,
    amount: float,
    currency: str = "MYR",
    description: str = "",
    user_id: str | None = None,
    org_id: str | None = None,
) -> dict[str, Any]:
    """Open (or return the existing) escrow hold for a booking."""
    pool = await db.get_pool()
    if pool is None:
        existing = next((h for h in _MEM.values() if h["booking_ref"] == booking_ref), None)
        if existing:
            return existing
        hold = {
            "id": uuid.uuid4().hex,
            "booking_ref": booking_ref,
            "amount": round(float(amount), 2),
            "currency": currency,
            "description": description,
            "released": 0.0,
            "refunded": 0.0,
            "status": "held",
            "created_at": _now(),
            "events": [],
        }
        _MEM[hold["id"]] = hold
        return hold

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM escrow_holds WHERE booking_ref = $1 ORDER BY created_at LIMIT 1",
            booking_ref,
        )
        if row:
            return await get_hold(str(row["id"])) or {}
        new_id = await conn.fetchval(
            """INSERT INTO escrow_holds (booking_ref, user_id, org_id, description, amount, currency)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            booking_ref,
            uuid.UUID(user_id) if user_id else None,
            uuid.UUID(org_id) if org_id else None,
            description,
            round(float(amount), 2),
            currency,
        )
        await _add_event_db(conn, str(new_id), "hold", amount, currency, "system", "Funds held in escrow on booking", "ledger", None)
    return await get_hold(str(new_id)) or {}


async def _add_event_db(conn, hold_id, kind, amount, currency, actor, reason, settlement, atlas_ref, meta=None):  # type: ignore[no-untyped-def]
    await conn.execute(
        """INSERT INTO escrow_events (hold_id, kind, amount, currency, actor, reason, settlement, atlas_ref, meta)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
        uuid.UUID(hold_id),
        kind,
        round(float(amount), 2),
        currency,
        actor,
        reason,
        settlement,
        atlas_ref,
        __import__("json").dumps(meta or {}),
    )


async def add_event(
    hold_id: str,
    *,
    kind: str,
    amount: float,
    currency: str = "MYR",
    actor: str = "agent",
    reason: str = "",
    settlement: str = "ledger",
    atlas_ref: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append a ledger event and roll the hold's released/refunded/status forward."""
    pool = await db.get_pool()
    if pool is None:
        hold = _MEM.get(hold_id)
        if not hold:
            return
        hold["events"].append(
            {"kind": kind, "amount": round(float(amount), 2), "currency": currency, "actor": actor,
             "reason": reason, "settlement": settlement, "atlas_ref": atlas_ref, "created_at": _now()}
        )
        _roll(hold, kind, amount)
        return

    async with pool.acquire() as conn:
        await _add_event_db(conn, hold_id, kind, amount, currency, actor, reason, settlement, atlas_ref, meta)
        if kind in ("release", "refund", "upcharge"):
            col = {"release": "released", "refund": "refunded", "upcharge": "amount"}[kind]
            await conn.execute(
                f"UPDATE escrow_holds SET {col} = {col} + $1, updated_at = now() WHERE id = $2",
                round(float(amount), 2),
                uuid.UUID(hold_id),
            )
        # Recompute status from the rolled figures.
        await conn.execute(
            """UPDATE escrow_holds SET status = CASE
                   WHEN refunded >= amount THEN 'refunded'
                   WHEN released >= amount THEN 'released'
                   WHEN released > 0 OR refunded > 0 THEN 'partial'
                   ELSE 'held' END,
               updated_at = now() WHERE id = $1""",
            uuid.UUID(hold_id),
        )


def _roll(hold: dict[str, Any], kind: str, amount: float) -> None:
    if kind == "release":
        hold["released"] = round(hold["released"] + float(amount), 2)
    elif kind == "refund":
        hold["refunded"] = round(hold["refunded"] + float(amount), 2)
    elif kind == "upcharge":
        hold["amount"] = round(hold["amount"] + float(amount), 2)
    if hold["refunded"] >= hold["amount"]:
        hold["status"] = "refunded"
    elif hold["released"] >= hold["amount"]:
        hold["status"] = "released"
    elif hold["released"] > 0 or hold["refunded"] > 0:
        hold["status"] = "partial"


async def get_hold(hold_id: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return _MEM.get(hold_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM escrow_holds WHERE id = $1", uuid.UUID(hold_id))
        if not row:
            return None
        events = await conn.fetch(
            "SELECT kind, amount, currency, actor, reason, settlement, atlas_ref, created_at "
            "FROM escrow_events WHERE hold_id = $1 ORDER BY created_at",
            uuid.UUID(hold_id),
        )
    hold = _row_to_hold(dict(row))
    hold["events"] = [_ev(dict(e)) for e in events]
    return hold


async def list_holds(limit: int = 25) -> list[dict[str, Any]]:
    pool = await db.get_pool()
    if pool is None:
        return sorted(_MEM.values(), key=lambda h: h["created_at"], reverse=True)[:limit]
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM escrow_holds ORDER BY created_at DESC LIMIT $1", limit)
    return [_row_to_hold(dict(r)) for r in rows]


def _row_to_hold(row: dict[str, Any]) -> dict[str, Any]:
    hold = {
        "id": str(row["id"]),
        "booking_ref": row["booking_ref"],
        "description": row.get("description"),
        "amount": float(row["amount"]),
        "currency": row["currency"],
        "released": float(row["released"]),
        "refunded": float(row["refunded"]),
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
    }
    hold["remaining"] = _remaining(hold)
    return hold


def _ev(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": row["kind"],
        "amount": float(row["amount"]),
        "currency": row["currency"],
        "actor": row["actor"],
        "reason": row["reason"],
        "settlement": row["settlement"],
        "atlas_ref": row["atlas_ref"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
    }
