"""Hotel bookings (Track B).

A booking passes the inventory firewall's atomic guard, records a hotel_bookings
row + an income transaction on the finance ledger, and notifies the property
manager over Telegram — all so the money and the room state can never drift.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth.deps import require_agency
from app.core import db
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/bookings", tags=["bookings"])

_DEFAULT_CAPACITY = 10


class BookRequest(BaseModel):
    listing_id: str
    guest_name: str
    guest_contact: str | None = None
    channel: str = "journava"
    check_in: str | None = None
    check_out: str | None = None
    nights: int | None = None


def _nights(check_in: str | None, check_out: str | None, fallback: int | None) -> int:
    if fallback:
        return max(1, int(fallback))
    try:
        if check_in and check_out:
            d = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
            return max(1, d)
    except ValueError:
        pass
    return 1


@router.post("")
async def create_booking(body: BookRequest, request: Request) -> dict[str, Any]:
    """Book a room (any authenticated user). Firewall-guarded; records finance +
    notifies the manager. Returns the booking or a blocked result."""
    from app.finance import record as finance_record
    from app.tools import telegram

    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    lid = uuid.UUID(body.listing_id)

    async with pool.acquire() as conn:
        listing = await conn.fetchrow(
            """SELECT l.id, l.title, l.price_amount, l.price_currency, l.capacity, l.org_id,
                      p.name AS property_name
               FROM supplier_listings l JOIN supplier_properties p ON p.id = l.property_id
               WHERE l.id = $1""",
            lid,
        )
        if not listing:
            return {"error": "Listing not found."}
        org_id = str(listing["org_id"])
        capacity = int(listing["capacity"] or _DEFAULT_CAPACITY)
        price = float(listing["price_amount"]) if listing["price_amount"] is not None else 0.0
        currency = listing["price_currency"] or "MYR"

        # Make sure the booking channel is tracked so the guard has something to lock.
        await conn.execute(
            """INSERT INTO channel_inventory (listing_id, org_id, channel, allocated, sold)
               VALUES ($1, $2, $3, $4, 0) ON CONFLICT (listing_id, channel) DO NOTHING""",
            lid, uuid.UUID(org_id), body.channel, capacity,
        )

        nights = _nights(body.check_in, body.check_out, body.nights)
        amount = round(price * nights, 2)

        async with conn.transaction():
            rows = await conn.fetch(
                "SELECT sold FROM channel_inventory WHERE listing_id = $1 FOR UPDATE", lid
            )
            total_sold = sum(int(r["sold"]) for r in rows)
            if total_sold >= capacity:
                return {
                    "status": "blocked",
                    "reason": "Sold out — the firewall prevented an oversell.",
                    "listing": listing["title"],
                }
            await conn.execute(
                "UPDATE channel_inventory SET sold = sold + 1, updated_at = now() WHERE listing_id = $1 AND channel = $2",
                lid, body.channel,
            )
            booking_id = await conn.fetchval(
                """INSERT INTO hotel_bookings
                       (org_id, listing_id, property_name, room_title, guest_name, guest_contact,
                        channel, check_in, check_out, nights, amount, currency)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING id""",
                uuid.UUID(org_id), lid, listing["property_name"], listing["title"],
                body.guest_name, body.guest_contact, body.channel,
                date.fromisoformat(body.check_in) if body.check_in else None,
                date.fromisoformat(body.check_out) if body.check_out else None,
                nights, amount, currency,
            )

    # Post income to the finance ledger + notify the manager (best-effort).
    tx_id = await finance_record(
        org_id=org_id, kind="income", amount=amount, currency=currency,
        reference=str(booking_id), counterparty=body.guest_name,
        description=f"Booking · {listing['title']} · {nights} night(s)",
    )
    try:
        await telegram.notify(
            f"🛎️ <b>New booking</b>\n{body.guest_name} booked <b>{listing['title']}</b> "
            f"({listing['property_name']}) via {body.channel} — {currency} {amount:,.2f} for {nights} night(s)."
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("booking notify failed: %s", exc)

    return {
        "status": "confirmed",
        "booking_id": str(booking_id),
        "amount": amount,
        "currency": currency,
        "nights": nights,
        "finance_tx": tx_id,
    }


def _booking(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "property_name": row["property_name"],
        "room_title": row["room_title"],
        "guest_name": row["guest_name"],
        "guest_contact": row["guest_contact"],
        "channel": row["channel"],
        "check_in": row["check_in"].isoformat() if row.get("check_in") else None,
        "check_out": row["check_out"].isoformat() if row.get("check_out") else None,
        "nights": row["nights"],
        "amount": float(row["amount"]),
        "currency": row["currency"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
    }


@router.get("")
async def list_bookings(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"bookings": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM hotel_bookings WHERE org_id = $1 ORDER BY created_at DESC LIMIT 200",
            uuid.UUID(agency["org_id"]),
        )
    return {"bookings": [_booking(dict(r)) for r in rows]}


@router.get("/calendar")
async def calendar(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    """Bookings keyed by check-in date, for a month-grid view."""
    pool = await db.get_pool()
    if pool is None:
        return {"days": {}}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT check_in, room_title, guest_name, amount, currency FROM hotel_bookings "
            "WHERE org_id = $1 AND check_in IS NOT NULL ORDER BY check_in",
            uuid.UUID(agency["org_id"]),
        )
    days: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        key = r["check_in"].isoformat()
        days.setdefault(key, []).append(
            {"room": r["room_title"], "guest": r["guest_name"], "amount": float(r["amount"]), "currency": r["currency"]}
        )
    return {"days": days}
