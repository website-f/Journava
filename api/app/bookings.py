"""Hotel bookings (Track B).

A booking passes the inventory firewall's atomic guard, records a hotel_bookings
row + an income transaction on the finance ledger, and notifies the property
manager over Telegram — all so the money and the room state can never drift.
"""

from __future__ import annotations

import json
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
    from app.tools import notify

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
        await notify.broadcast(
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


async def send_due_reminders(*, days_ahead: int = 2, org_id: str | None = None) -> dict[str, Any]:
    """Notify managers of upcoming check-ins not yet reminded. Marks reminded_at
    so each booking is only pinged once. Runs org-scoped (manual) or globally
    (the periodic task)."""
    from app.tools import notify

    pool = await db.get_pool()
    if pool is None:
        return {"sent": 0, "bookings": []}
    clause = "status <> 'cancelled' AND reminded_at IS NULL AND check_in IS NOT NULL " \
             f"AND check_in <= (current_date + interval '{int(days_ahead)} days') AND check_in >= current_date"
    args: list[Any] = []
    if org_id:
        args.append(uuid.UUID(org_id))
        clause += f" AND org_id = ${len(args)}"
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"SELECT * FROM hotel_bookings WHERE {clause} ORDER BY check_in LIMIT 100", *args)

    sent = 0
    done: list[dict[str, Any]] = []
    for r in rows:
        b = _booking(dict(r))
        text = (
            f"⏰ <b>Check-in reminder</b>\n{b['guest_name']} arrives <b>{b['check_in']}</b> at "
            f"{b['property_name']} — {b['room_title']} ({b['nights']} night(s))."
        )
        try:
            await notify.broadcast(text)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.info("reminder notify failed: %s", exc)
        async with pool.acquire() as conn:
            await conn.execute("UPDATE hotel_bookings SET reminded_at = now() WHERE id = $1", uuid.UUID(b["id"]))
        done.append({"guest": b["guest_name"], "check_in": b["check_in"], "room": b["room_title"]})
    return {"sent": sent, "bookings": done}


@router.post("/remind-due")
async def remind_due(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    """Manually run the check-in reminder sweep for this org (demo-friendly)."""
    return await send_due_reminders(days_ahead=7, org_id=agency["org_id"])


def _trip_start_date(snap: dict[str, Any]) -> date | None:
    """The canonical trip start from a saved snapshot (chief.data.start_date),
    parsed to a date. Returns None when the trip has no fixed start."""
    chief = snap.get("chief") if isinstance(snap, dict) else None
    data = (chief.get("data") if isinstance(chief, dict) else {}) or {}
    raw = data.get("start_date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _day_one_highlight(snap: dict[str, Any]) -> str | None:
    """A single teaser line for the countdown — the first scheduled activity."""
    items = (snap.get("itinerary") or {}).get("items") or []
    for it in items:
        title = (it.get("title") or it.get("name") or "").strip()
        if title:
            return title
    return None


def _countdown_phrase(days: int) -> str:
    if days <= 0:
        return "is <b>today</b> 🎉"
    if days == 1:
        return "is <b>tomorrow</b>"
    return f"is in <b>{days} days</b>"


async def send_trip_countdowns(*, days_ahead: int = 3) -> dict[str, Any]:
    """Ping travellers about a saved trip whose start date is near, exactly once.

    Mirrors ``send_due_reminders``: marks ``saved_results.notified_at`` so each
    trip fires a single countdown instead of every cycle. Trips with no fixed
    start date are left untouched (so a countdown fires once dates are added);
    trips already in the past are marked notified silently so they stop being
    re-scanned. Runs globally (the periodic task) with a demo-friendly manual
    trigger below.
    """
    from app.tools import notify

    pool = await db.get_pool()
    if pool is None:
        return {"sent": 0, "trips": []}

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, destination, snapshot FROM saved_results "
            "WHERE kind = 'trip' AND notified_at IS NULL ORDER BY created_at DESC LIMIT 200"
        )

    today = date.today()
    sent = 0
    done: list[dict[str, Any]] = []
    for r in rows:
        snap = r["snapshot"]
        try:
            snap = json.loads(snap) if isinstance(snap, str) else (snap or {})
        except (ValueError, TypeError):
            snap = {}
        start = _trip_start_date(snap)
        if start is None:
            continue  # no dates yet — revisit next cycle, don't mark
        days_until = (start - today).days
        if days_until > days_ahead:
            continue  # too far out — leave for a future cycle
        # Past trips fall through and get marked (silent) so we stop scanning them.
        if 0 <= days_until <= days_ahead:
            dest = r["destination"] or r["title"] or "your trip"
            highlight = _day_one_highlight(snap)
            text = (
                f"✈️ <b>Trip countdown</b>\nYour trip to <b>{dest}</b> "
                f"{_countdown_phrase(days_until)}!"
            )
            if highlight:
                text += f"\nFirst up: {highlight}."
            text += "\nOpen Journava to review your plan and bookings."
            try:
                await notify.broadcast(text)
                sent += 1
                done.append({"destination": dest, "start_date": start.isoformat(), "days_until": days_until})
            except Exception as exc:  # noqa: BLE001
                logger.info("countdown notify failed: %s", exc)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE saved_results SET notified_at = now() WHERE id = $1", r["id"]
            )
    return {"sent": sent, "trips": done}


@router.post("/notify-countdowns")
async def notify_countdowns(request: Request) -> dict[str, Any]:
    """Manually run the trip-countdown sweep (demo-friendly, any authed user)."""
    return await send_trip_countdowns(days_ahead=3)


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
