"""Consumer trip bookings — mark a flight/hotel as booked and see it as booked.

Most consumer bookings happen off-platform (the traveller clicks through to an OTA
via the compare links, or books a hotel directly), so Journava lets them *mark* an
option booked: the card then locks to a "Booked · ref · view details" state instead
of offering to book again. Marks are content-keyed (item_key), so the same booked
flight/hotel shows as booked in the live trip AND in the saved/history snapshot.
Everything is scoped to the signed-in user. No real money moves here.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core import db
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=settings.api_prefix, tags=["trip-bookings"])


def _user_id(request: Request) -> str | None:
    return (getattr(request.state, "auth", {}) or {}).get("sub")


class MarkRequest(BaseModel):
    item_kind: str                       # flight | hotel
    item_key: str                        # stable content key from the option
    direction: str = ""                  # outbound | return (flights)
    title: str | None = None
    provider: str | None = None
    price_amount: float | None = None
    price_currency: str | None = None
    booking_ref: str | None = None
    check_in: str | None = None          # ISO date (hotels)
    source: str | None = None            # external | atlas
    trip_id: str | None = None
    snapshot: dict[str, Any] | None = None


def _row(r: dict[str, Any]) -> dict[str, Any]:
    snap = r.get("snapshot")
    if isinstance(snap, str):
        try:
            snap = json.loads(snap)
        except (ValueError, TypeError):
            snap = None
    return {
        "id": str(r["id"]),
        "item_kind": r.get("item_kind"),
        "direction": r.get("direction") or "",
        "item_key": r.get("item_key"),
        "title": r.get("title"),
        "provider": r.get("provider"),
        "price_amount": float(r["price_amount"]) if r.get("price_amount") is not None else None,
        "price_currency": r.get("price_currency"),
        "booking_ref": r.get("booking_ref"),
        "status": r.get("status") or "booked",
        "check_in": r["check_in"].isoformat() if r.get("check_in") else None,
        "source": r.get("source"),
        "snapshot": snap,
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


@router.get("/trip/bookings")
async def list_bookings(request: Request) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"bookings": []}
    uid = _user_id(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM trip_bookings WHERE (user_id = $1 OR $1 IS NULL) ORDER BY created_at DESC LIMIT 200",
            uuid.UUID(uid) if uid else None,
        )
    return {"bookings": [_row(dict(r)) for r in rows]}


@router.post("/trip/bookings")
async def mark_booking(body: MarkRequest, request: Request) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    uid = _user_id(request)
    ref = (body.booking_ref or "").strip() or "JV-" + secrets.token_hex(3).upper()
    check_in = None
    if body.check_in:
        try:
            check_in = date.fromisoformat(body.check_in[:10])
        except ValueError:
            check_in = None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO trip_bookings
                   (user_id, trip_id, item_kind, direction, item_key, title, provider,
                    price_amount, price_currency, booking_ref, check_in, source, snapshot)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT (user_id, item_key, direction) DO UPDATE SET
                   title = EXCLUDED.title, provider = EXCLUDED.provider,
                   price_amount = EXCLUDED.price_amount, price_currency = EXCLUDED.price_currency,
                   booking_ref = COALESCE(trip_bookings.booking_ref, EXCLUDED.booking_ref),
                   check_in = EXCLUDED.check_in, source = EXCLUDED.source, snapshot = EXCLUDED.snapshot
               RETURNING *""",
            uuid.UUID(uid) if uid else None,
            uuid.UUID(body.trip_id) if body.trip_id else None,
            body.item_kind, (body.direction or "")[:16], body.item_key[:300],
            body.title, body.provider,
            body.price_amount, body.price_currency, ref, check_in, (body.source or "external"),
            json.dumps(body.snapshot) if body.snapshot is not None else None,
        )
    return {"booking": _row(dict(row))}


@router.delete("/trip/bookings/{booking_id}")
async def unmark_booking(booking_id: str, request: Request) -> dict[str, bool]:
    pool = await db.get_pool()
    if pool is None:
        return {"removed": False}
    uid = _user_id(request)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM trip_bookings WHERE id = $1 AND (user_id = $2 OR $2 IS NULL)",
            uuid.UUID(booking_id), uuid.UUID(uid) if uid else None,
        )
    return {"removed": result.endswith("1")}
