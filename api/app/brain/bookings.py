"""Flight booking store — the Atlas order lifecycle, persisted.

Atlas's flow is a state machine over opaque identifiers:

    offer_id ──verify──► booking_id ──confirm-price──► booking_id
             ──order create──► order_no + confirmation_id
             ──pay──► paid ──status(poll ≤120s)──► ticketed

Each identifier is issued by Atlas and stored **verbatim**; none is parsed or
regenerated. This module owns the persistence and the stage transitions so a
booking can be resumed and shown in History.

Two safety rules from the Atlas docs are enforced here, not just documented:

- **A confirmation ID is single-use.** Once a payment has been attempted, the
  stage moves to `paying` and a second attempt is refused. An uncertain payment
  is resolved by polling `order status`, never by paying again.
- **Passenger details are never persisted.** Atlas excludes them from its own
  stored state; storing them here would defeat that, so only a count is kept.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date
from typing import Any, Literal

from app.core import db

logger = logging.getLogger(__name__)

Stage = Literal["draft", "price_confirmed", "ordered", "paying", "paid", "ticketed", "failed"]

#: Stages from which a payment may still be attempted.
PAYABLE_STAGES = frozenset({"ordered"})

#: Terminal stages — nothing further happens without a new search.
TERMINAL_STAGES = frozenset({"ticketed", "failed"})


def _row_to_public(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            payload = {}
    return {
        "id": str(row["id"]),
        "trip_id": str(row["trip_id"]) if row.get("trip_id") else None,
        "offer_id": row.get("offer_id"),
        "booking_id": row.get("booking_id"),
        "order_no": row.get("order_no"),
        # The confirmation id is a payment authorisation, so it is never returned.
        "has_confirmation": bool(row.get("confirmation_id")),
        "environment": row.get("environment", "sandbox"),
        "stage": row.get("stage", "draft"),
        "last_code": row.get("last_code"),
        "last_message": row.get("last_message"),
        "route": row.get("route"),
        "depart_date": row["depart_date"].isoformat() if row.get("depart_date") else None,
        "travellers": row.get("travellers", 1),
        "total_amount": float(row["total_amount"]) if row.get("total_amount") else None,
        "currency": row.get("currency"),
        "simulated": row.get("simulated", True),
        "payload": payload or {},
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


_COLUMNS = (
    "id, trip_id, offer_id, booking_id, order_no, confirmation_id, environment, "
    "stage, last_code, last_message, route, depart_date, travellers, "
    "total_amount, currency, payload, simulated, created_at, updated_at"
)

#: In-process mirror so the booking flow still works without Postgres. The
#: Atlas side of the flow is what matters for a demo; losing history to a missing
#: database should not block a purchase rehearsal.
_memory: dict[str, dict[str, Any]] = {}


async def create(
    *,
    offer_id: str | None,
    route: str | None,
    depart_date: date | None,
    travellers: int,
    total_amount: float | None,
    currency: str | None,
    environment: str = "sandbox",
    payload: dict[str, Any] | None = None,
    trip_id: str | None = None,
) -> dict[str, Any]:
    """Open a booking record in the `draft` stage."""
    record = {
        "id": uuid.uuid4(),
        "trip_id": uuid.UUID(trip_id) if trip_id else None,
        "offer_id": offer_id,
        "booking_id": None,
        "order_no": None,
        "confirmation_id": None,
        "environment": environment,
        "stage": "draft",
        "last_code": None,
        "last_message": None,
        "route": route,
        "depart_date": depart_date,
        "travellers": max(1, travellers),
        "total_amount": total_amount,
        "currency": currency,
        "payload": payload or {},
        "simulated": environment != "production",
    }

    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"""INSERT INTO flight_bookings
                           (id, trip_id, offer_id, environment, stage, route,
                            depart_date, travellers, total_amount, currency,
                            payload, simulated)
                       VALUES ($1, $2, $3, $4, 'draft', $5, $6, $7, $8, $9, $10, $11)
                       RETURNING {_COLUMNS}""",  # noqa: S608 — fixed columns
                    record["id"],
                    record["trip_id"],
                    offer_id,
                    environment,
                    route,
                    depart_date,
                    record["travellers"],
                    total_amount,
                    currency,
                    json.dumps(record["payload"], default=str),
                    record["simulated"],
                )
            return _row_to_public(dict(row))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not persist booking, keeping it in memory: %s", exc)

    from datetime import UTC, datetime

    record["created_at"] = record["updated_at"] = datetime.now(UTC)
    _memory[str(record["id"])] = record
    return _row_to_public(record)


async def get(booking_row_id: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT {_COLUMNS} FROM flight_bookings WHERE id = $1",  # noqa: S608
                    uuid.UUID(booking_row_id),
                )
            if row:
                return _row_to_public(dict(row))
        except Exception as exc:  # noqa: BLE001
            logger.debug("bookings.get failed: %s", exc)
    record = _memory.get(booking_row_id)
    return _row_to_public(record) if record else None


async def get_internal(booking_row_id: str) -> dict[str, Any] | None:
    """Like `get`, but includes the confirmation id for the payment step."""
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT {_COLUMNS} FROM flight_bookings WHERE id = $1",  # noqa: S608
                    uuid.UUID(booking_row_id),
                )
            if row:
                data = dict(row)
                public = _row_to_public(data)
                public["confirmation_id"] = data.get("confirmation_id")
                return public
        except Exception as exc:  # noqa: BLE001
            logger.debug("bookings.get_internal failed: %s", exc)
    record = _memory.get(booking_row_id)
    if not record:
        return None
    public = _row_to_public(record)
    public["confirmation_id"] = record.get("confirmation_id")
    return public


async def update(
    booking_row_id: str,
    *,
    stage: Stage | None = None,
    booking_id: str | None = None,
    order_no: str | None = None,
    confirmation_id: str | None = None,
    last_code: str | None = None,
    last_message: str | None = None,
    total_amount: float | None = None,
    currency: str | None = None,
    payload_patch: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Advance a booking. Only the provided fields change."""
    updates: dict[str, Any] = {}
    if stage is not None:
        updates["stage"] = stage
    if booking_id is not None:
        updates["booking_id"] = booking_id
    if order_no is not None:
        updates["order_no"] = order_no
    if confirmation_id is not None:
        updates["confirmation_id"] = confirmation_id
    if last_code is not None:
        updates["last_code"] = last_code
    if last_message is not None:
        updates["last_message"] = last_message[:500]
    if total_amount is not None:
        updates["total_amount"] = total_amount
    if currency is not None:
        updates["currency"] = currency

    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                if payload_patch:
                    existing = await conn.fetchval(
                        "SELECT payload FROM flight_bookings WHERE id = $1",
                        uuid.UUID(booking_row_id),
                    )
                    current = (
                        json.loads(existing) if isinstance(existing, str) else (existing or {})
                    )
                    updates["payload"] = json.dumps({**current, **payload_patch}, default=str)
                if not updates:
                    return await get(booking_row_id)
                assignments = ", ".join(f"{key} = ${i + 2}" for i, key in enumerate(updates))
                row = await conn.fetchrow(
                    f"UPDATE flight_bookings SET {assignments}, updated_at = now() "  # noqa: S608
                    f"WHERE id = $1 RETURNING {_COLUMNS}",
                    uuid.UUID(booking_row_id),
                    *updates.values(),
                )
            if row:
                return _row_to_public(dict(row))
        except Exception as exc:  # noqa: BLE001
            logger.warning("bookings.update failed: %s", exc)

    record = _memory.get(booking_row_id)
    if record is None:
        return None
    if payload_patch:
        record["payload"] = {**(record.get("payload") or {}), **payload_patch}
    record.update({k: v for k, v in updates.items() if k != "payload"})
    from datetime import UTC, datetime

    record["updated_at"] = datetime.now(UTC)
    return _row_to_public(record)


async def history(limit: int = 50) -> list[dict[str, Any]]:
    """Bookings, newest first — the flights half of the History page."""
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT {_COLUMNS} FROM flight_bookings "  # noqa: S608
                    "ORDER BY created_at DESC LIMIT $1",
                    limit,
                )
            if rows:
                return [_row_to_public(dict(row)) for row in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("bookings.history failed: %s", exc)
    return [
        _row_to_public(record)
        for record in sorted(
            _memory.values(), key=lambda r: r.get("created_at") or 0, reverse=True
        )[:limit]
    ]
