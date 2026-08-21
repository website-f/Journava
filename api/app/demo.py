"""One-command demo seed — so every panel has content on stage.

Idempotently populates the caller's org with: a saved active trip, a supplier
property + room, an over-allocated firewall listing, a near-term booking (so
check-in reminders fire), an open escrow hold, a client, and a few finance
transactions (income + a refund). De-risks the live demo — no empty states.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.auth.deps import require_agency
from app.brain import escrow_store, trip_store
from app.core import db
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/demo", tags=["demo"])

_DEMO_LISTING = "Firewall Demo — Deluxe Room"
_CHANNELS = [("journava", 2, 1), ("booking.com", 2, 1), ("agoda", 1, 0)]  # over-allocated (5 > 3)


@router.post("/seed")
async def seed(request: Request, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    org_id = agency["org_id"]
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    summary: dict[str, Any] = {}

    # 1. Active trip (so My Trip + escrow-from-trip aren't empty).
    if await trip_store.load_trip_durable() is None:
        try:
            from app.brain.demo_trip import get_demo_trip

            trip_store.save_trip(get_demo_trip())
            summary["trip"] = "seeded (Venice demo)"
        except Exception as exc:  # noqa: BLE001
            logger.info("demo trip seed skipped: %s", exc)
            summary["trip"] = "skipped"
    else:
        summary["trip"] = "already present"

    async with pool.acquire() as conn:
        # 2. Property + over-allocated listing (firewall demo).
        listing = await conn.fetchrow(
            "SELECT id, capacity FROM supplier_listings WHERE org_id = $1 AND title = $2",
            uuid.UUID(org_id), _DEMO_LISTING,
        )
        if not listing:
            prop_id = await conn.fetchval(
                "SELECT id FROM supplier_properties WHERE org_id = $1 ORDER BY created_at LIMIT 1",
                uuid.UUID(org_id),
            ) or await conn.fetchval(
                """INSERT INTO supplier_properties (org_id, name, kind, city, country, halal_friendly)
                   VALUES ($1, 'Demo Bayfront Resort', 'hotel', 'Kota Kinabalu', 'Malaysia', TRUE)
                   RETURNING id""",
                uuid.UUID(org_id),
            )
            listing_id = await conn.fetchval(
                """INSERT INTO supplier_listings (property_id, org_id, title, price_amount, price_currency, capacity, available)
                   VALUES ($1, $2, $3, 420, 'MYR', 3, TRUE) RETURNING id""",
                prop_id, uuid.UUID(org_id), _DEMO_LISTING,
            )
        else:
            listing_id = listing["id"]
            await conn.execute("UPDATE supplier_listings SET capacity = 3 WHERE id = $1", listing_id)
        for channel, allocated, sold in _CHANNELS:
            await conn.execute(
                """INSERT INTO channel_inventory (listing_id, org_id, channel, allocated, sold)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT (listing_id, channel) DO UPDATE SET allocated = EXCLUDED.allocated, sold = EXCLUDED.sold""",
                listing_id, uuid.UUID(org_id), channel, allocated, sold,
            )
        summary["firewall_listing"] = "over-allocated (5 across channels / 3 rooms)"

        # 3. A near-term booking (check-in tomorrow) so reminders fire.
        existing_booking = await conn.fetchval(
            "SELECT id FROM hotel_bookings WHERE org_id = $1 AND guest_name = 'Demo Guest' LIMIT 1",
            uuid.UUID(org_id),
        )
        if not existing_booking:
            booking_id = await conn.fetchval(
                """INSERT INTO hotel_bookings
                       (org_id, listing_id, property_name, room_title, guest_name, guest_contact,
                        channel, check_in, check_out, nights, amount, currency)
                   VALUES ($1,$2,'Demo Bayfront Resort',$3,'Demo Guest','demo@example.com',
                           'journava', current_date + 1, current_date + 3, 2, 840, 'MYR')
                   RETURNING id""",
                uuid.UUID(org_id), listing_id, _DEMO_LISTING,
            )
        else:
            booking_id = existing_booking
        summary["near_term_booking"] = "check-in tomorrow (reminder-ready)"

        # 5. A client.
        client_exists = await conn.fetchval(
            "SELECT 1 FROM agency_clients WHERE org_id = $1 AND name = 'Demo Client' LIMIT 1",
            uuid.UUID(org_id),
        )
        if not client_exists:
            await conn.execute(
                """INSERT INTO agency_clients (org_id, name, email, channel, notes)
                   VALUES ($1, 'Demo Client', 'client@example.com', 'telegram', 'family of 4, halal')""",
                uuid.UUID(org_id),
            )
        summary["client"] = "Demo Client ready"

        # 6. Finance: ensure at least one income + one refund row exist.
        fin_count = await conn.fetchval("SELECT count(*) FROM finance_transactions WHERE org_id = $1", uuid.UUID(org_id))
        if int(fin_count or 0) < 2:
            await conn.execute(
                """INSERT INTO finance_transactions (org_id, kind, amount, currency, reference, counterparty, description)
                   VALUES ($1,'income',840,'MYR',$2,'Demo Guest','Booking · Deluxe Room · 2 nights'),
                          ($1,'refund',126,'MYR',$2,'traveller','AI-adjudicated refund (15%) — flight_delayed')""",
                uuid.UUID(org_id), str(booking_id),
            )
        summary["finance"] = "income + refund rows present"

    # 4. An open escrow hold (for the adjudicator demo).
    try:
        hold = await escrow_store.open_hold(
            booking_ref=str(booking_id), amount=840, currency="MYR",
            description="Demo booking hold", org_id=org_id,
        )
        summary["escrow_hold"] = f"open ({hold.get('status')})"
    except Exception as exc:  # noqa: BLE001
        logger.info("demo escrow seed skipped: %s", exc)
        summary["escrow_hold"] = "skipped"

    return {"ready": True, "seeded": summary}
