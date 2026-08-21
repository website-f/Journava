"""Hotel inventory firewall API (Tier 3).

Reconciles a supplier's room state across channels and — the point — guards a
booking *atomically* so two channels can't sell the last room. The booking guard
uses a Postgres row lock (SELECT … FOR UPDATE), so concurrent bookings serialize
and exactly one wins when a single room remains.

Flights are real via Atlas; hotels are our own supplier inventory, so this is
the layer we genuinely own. A Camofox cross-check reads an OTA's public
availability and compares it to our source of truth ("Camofox where Atlas can't").
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.auth.deps import resolve_org_id
from app.core import db
from app.core.settings import settings
from app.tools import camofox, inventory_firewall

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/firewall", tags=["firewall"])

_DEMO_TITLE = "Firewall Demo — Deluxe Room"
_DEMO_CHANNELS = [("journava", 2, 1), ("booking.com", 2, 1), ("agoda", 1, 0)]  # (channel, allocated, sold)


class BookRequest(BaseModel):
    listing_id: str
    channel: str = "journava"


class ListingRef(BaseModel):
    listing_id: str
    url: str | None = None


async def _org_listings(conn, org_id: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """SELECT l.id, l.title, l.capacity, l.price_amount, l.price_currency, p.name AS property
           FROM supplier_listings l JOIN supplier_properties p ON p.id = l.property_id
           WHERE l.org_id = $1 ORDER BY l.created_at""",
        uuid.UUID(org_id),
    )
    return [dict(r) for r in rows]


async def _channels(conn, listing_id) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT channel, allocated, sold FROM channel_inventory WHERE listing_id = $1 ORDER BY channel",
        listing_id,
    )
    return [dict(r) for r in rows]


@router.post("/seed")
async def seed(request: Request) -> dict[str, Any]:
    """Idempotently create a demo listing + over-allocated channels for the org."""
    org_id = await resolve_org_id(request)
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    async with pool.acquire() as conn:
        listing = await conn.fetchrow(
            "SELECT id FROM supplier_listings WHERE org_id = $1 AND title = $2",
            uuid.UUID(org_id), _DEMO_TITLE,
        )
        if not listing:
            prop_id = await conn.fetchval(
                "SELECT id FROM supplier_properties WHERE org_id = $1 ORDER BY created_at LIMIT 1",
                uuid.UUID(org_id),
            )
            if not prop_id:
                prop_id = await conn.fetchval(
                    """INSERT INTO supplier_properties (org_id, name, kind, city, country)
                       VALUES ($1, 'Firewall Demo Property', 'hotel', 'Kota Kinabalu', 'Malaysia')
                       RETURNING id""",
                    uuid.UUID(org_id),
                )
            listing_id = await conn.fetchval(
                """INSERT INTO supplier_listings (property_id, org_id, title, price_amount, price_currency, capacity, available)
                   VALUES ($1, $2, $3, 380, 'MYR', 3, TRUE) RETURNING id""",
                prop_id, uuid.UUID(org_id), _DEMO_TITLE,
            )
        else:
            listing_id = listing["id"]
            await conn.execute("UPDATE supplier_listings SET capacity = 3 WHERE id = $1", listing_id)
            await conn.execute("DELETE FROM channel_inventory WHERE listing_id = $1", listing_id)
        for channel, allocated, sold in _DEMO_CHANNELS:
            await conn.execute(
                """INSERT INTO channel_inventory (listing_id, org_id, channel, allocated, sold)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (listing_id, channel) DO UPDATE SET allocated = EXCLUDED.allocated, sold = EXCLUDED.sold""",
                listing_id, uuid.UUID(org_id), channel, allocated, sold,
            )
    return {"listing_id": str(listing_id), "seeded": True}


@router.get("/state")
async def state(request: Request) -> dict[str, Any]:
    """Every listing + its channels + the firewall's reconciliation diagnosis."""
    org_id = await resolve_org_id(request)
    pool = await db.get_pool()
    if pool is None:
        return {"listings": []}
    async with pool.acquire() as conn:
        listings = await _org_listings(conn, org_id)
        out = []
        for lst in listings:
            channels = await _channels(conn, lst["id"])
            diag = inventory_firewall.reconcile(int(lst["capacity"] or 0), channels)
            out.append(
                {
                    "listing_id": str(lst["id"]),
                    "title": lst["title"],
                    "property": lst["property"],
                    "capacity": lst["capacity"],
                    "channels": channels,
                    **diag,
                }
            )
    return {"listings": out}


@router.post("/reconcile")
async def reconcile(request: Request) -> dict[str, Any]:
    """Apply the firewall's fixes (close-outs / rebalances) across the org."""
    org_id = await resolve_org_id(request)
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    applied: list[dict[str, Any]] = []
    async with pool.acquire() as conn:
        for lst in await _org_listings(conn, org_id):
            channels = await _channels(conn, lst["id"])
            diag = inventory_firewall.reconcile(int(lst["capacity"] or 0), channels)
            for fix in diag["fixes"]:
                await conn.execute(
                    "UPDATE channel_inventory SET allocated = $1, updated_at = now() WHERE listing_id = $2 AND channel = $3",
                    fix["new_allocated"], lst["id"], fix["channel"],
                )
                applied.append({"listing": lst["title"], **fix})
    return {"fixes_applied": applied, "count": len(applied)}


async def _guarded_book(conn, listing_id: uuid.UUID, channel: str) -> dict[str, Any]:
    """Atomic booking guard inside a transaction (rows are already FOR UPDATE)."""
    rows = await conn.fetch(
        "SELECT channel, allocated, sold FROM channel_inventory WHERE listing_id = $1 FOR UPDATE",
        listing_id,
    )
    capacity = await conn.fetchval("SELECT capacity FROM supplier_listings WHERE id = $1", listing_id)
    capacity = int(capacity or 0)
    total_sold = sum(int(r["sold"]) for r in rows)
    if total_sold >= capacity:
        return {
            "status": "blocked",
            "channel": channel,
            "reason": "Sold out — firewall prevented a double-booking.",
            "physical_available": 0,
        }
    updated = await conn.execute(
        "UPDATE channel_inventory SET sold = sold + 1, updated_at = now() WHERE listing_id = $1 AND channel = $2",
        listing_id, channel,
    )
    if updated.endswith("0"):
        return {"status": "blocked", "channel": channel, "reason": f"Channel '{channel}' not on this listing."}
    return {"status": "confirmed", "channel": channel, "physical_available": capacity - total_sold - 1}


@router.post("/book")
async def book(body: BookRequest) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    async with pool.acquire() as conn:
        async with conn.transaction():
            return await _guarded_book(conn, uuid.UUID(body.listing_id), body.channel)


@router.post("/simulate-race")
async def simulate_race(body: ListingRef) -> dict[str, Any]:
    """Force the listing to one remaining room, then fire two concurrent bookings
    from different channels. The firewall lets exactly one through."""
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    lid = uuid.UUID(body.listing_id)
    async with pool.acquire() as conn:
        capacity = int(await conn.fetchval("SELECT capacity FROM supplier_listings WHERE id = $1", lid) or 0)
        channels = await _channels(conn, lid)
        if len(channels) < 2 or capacity < 1:
            return {"error": "need >=2 channels and capacity >=1; run /firewall/seed first"}
        # Set total sold = capacity - 1 (one room left), spread onto the first channels.
        target_sold = capacity - 1
        for i, c in enumerate(channels):
            new_sold = 1 if (i < target_sold) else 0
            await conn.execute(
                "UPDATE channel_inventory SET sold = $1 WHERE listing_id = $2 AND channel = $3",
                new_sold, lid, c["channel"],
            )

    ch_a, ch_b = channels[0]["channel"], channels[1]["channel"]

    async def _book(channel: str) -> dict[str, Any]:
        async with pool.acquire() as conn:
            async with conn.transaction():
                return await _guarded_book(conn, lid, channel)

    results = await asyncio.gather(_book(ch_a), _book(ch_b))
    confirmed = [r for r in results if r["status"] == "confirmed"]
    blocked = [r for r in results if r["status"] == "blocked"]
    return {
        "capacity": capacity,
        "room_left_before": 1,
        "attempts": results,
        "double_booking_prevented": len(confirmed) == 1 and len(blocked) == 1,
        "summary": f"{len(confirmed)} confirmed, {len(blocked)} blocked by the firewall.",
    }


@router.post("/crosscheck")
async def crosscheck(body: ListingRef) -> dict[str, Any]:
    """Best-effort: read an OTA page's public availability via Camofox and compare
    to our source of truth. Camofox handles what Atlas (flights-only) can't."""
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    lid = uuid.UUID(body.listing_id)
    async with pool.acquire() as conn:
        capacity = int(await conn.fetchval("SELECT capacity FROM supplier_listings WHERE id = $1", lid) or 0)
        title = await conn.fetchval("SELECT title FROM supplier_listings WHERE id = $1", lid)
        channels = await _channels(conn, lid)
    physical_available = max(0, capacity - sum(int(c["sold"]) for c in channels))

    url = body.url or f"https://www.google.com/search?q={(title or 'hotel').replace(' ', '+')}+availability"
    ota_shows_available: bool | None = None
    try:
        snapshot = await camofox.browse(url, ready=r"(?i)(available|sold out|no rooms|book now)", attempts=3)
        if snapshot:
            low = snapshot.lower()
            if "sold out" in low or "no rooms" in low:
                ota_shows_available = False
            elif "available" in low or "book now" in low:
                ota_shows_available = True
    except Exception as exc:  # noqa: BLE001
        logger.info("firewall crosscheck crawl failed: %s", exc)

    drift = ota_shows_available is True and physical_available == 0
    return {
        "listing_id": body.listing_id,
        "our_physical_available": physical_available,
        "ota_shows_available": ota_shows_available,
        "checked": ota_shows_available is not None,
        "drift_detected": drift,
        "recommendation": "Push a close-out to the OTA — it is selling rooms we no longer have."
        if drift
        else "In sync." if ota_shows_available is not None else "Could not read the OTA page.",
        "source_url": url,
    }
