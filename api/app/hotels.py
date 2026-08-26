"""Direct hotel sites — a business's own public, bookable storefront.

The owner sets a company profile (logo + about + a slug), publishes, and gets a
link like /h/{slug}: a Booking.com-style page of THEIR rooms — images, prices,
discounts, amenities — that a traveller books directly (no OTA in the middle).
Payment is simulated (no real gateway) and every booking passes the same atomic
double-booking guard the console uses, so two guests can't take the last room.

- `config_router` (/agency/profile, authed) — the owner edits + publishes.
- `public_router` (/hotels/*, allowlisted) — the storefront + booking.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.deps import require_agency
from app.core import db
from app.core.settings import settings
from app.supplier import store as supplier_store

logger = logging.getLogger("journava")

config_router = APIRouter(prefix=f"{settings.api_prefix}/agency", tags=["hotel-profile"])
public_router = APIRouter(prefix=f"{settings.api_prefix}/hotels", tags=["hotels"])

_DEFAULT_CAPACITY = 10


def _slugify(name: str) -> str:
    base = "".join(c if c.isalnum() else "-" for c in (name or "hotel").lower()).strip("-")
    base = "-".join(p for p in base.split("-") if p)[:40] or "hotel"
    return f"{base}-{secrets.token_hex(2)}"


async def _get_or_create_profile(org_id: str, org_name: str | None) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM org_profiles WHERE org_id = $1", org_id)
        if row is None:
            row = await conn.fetchrow(
                """INSERT INTO org_profiles (org_id, slug, name, about, published)
                   VALUES ($1,$2,$3,$4,TRUE) RETURNING *""",
                org_id,
                _slugify(org_name or "hotel"),
                org_name,
                "Book direct with us for the best rates, with no OTA booking fees.",
            )
    return dict(row)


def _profile_public(row: dict[str, Any]) -> dict[str, Any]:
    base = (settings.public_base_url or "").rstrip("/")
    return {
        "slug": row["slug"],
        "name": row.get("name"),
        "logo_url": row.get("logo_url"),
        "about": row.get("about"),
        "published": row.get("published", True),
        "url": f"{base}/h/{row['slug']}" if base else f"/h/{row['slug']}",
    }


class ProfileUpdate(BaseModel):
    name: str | None = None
    logo_url: str | None = None
    about: str | None = None
    published: bool | None = None


@config_router.get("/profile")
async def get_profile(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    row = await _get_or_create_profile(agency["org_id"], agency.get("org_name"))
    return {"profile": _profile_public(row)}


@config_router.post("/profile")
async def update_profile(body: ProfileUpdate, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    await _get_or_create_profile(agency["org_id"], agency.get("org_name"))
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE org_profiles SET
                   name = COALESCE($2, name),
                   logo_url = COALESCE($3, logo_url),
                   about = COALESCE($4, about),
                   published = COALESCE($5, published)
               WHERE org_id = $1 RETURNING *""",
            agency["org_id"], body.name, body.logo_url, body.about, body.published,
        )
    return {"profile": _profile_public(dict(row))}


# --------------------------------------------------------------------------- #
# Public storefront + booking
# --------------------------------------------------------------------------- #


async def _profile_by_slug(slug: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM org_profiles WHERE slug = $1", slug)
    return dict(row) if row else None


@public_router.get("/{slug}")
async def public_site(slug: str) -> dict[str, Any]:
    """The public storefront: profile + every published room, bookable."""
    profile = await _profile_by_slug(slug)
    if not profile or not profile.get("published"):
        return {"found": False}
    properties = await supplier_store.list_properties(profile["org_id"])
    # Flatten to bookable rooms (only available ones), carrying their property.
    rooms: list[dict[str, Any]] = []
    for prop in properties:
        for lst in prop.get("listings", []):
            if not lst.get("available"):
                continue
            rooms.append({
                **lst,
                "property_name": prop["name"],
                "city": prop["city"],
                "property_image": prop.get("image_url"),
                "halal_friendly": prop.get("halal_friendly"),
                "star_rating": prop.get("star_rating"),
            })
    cities = sorted({p["city"] for p in properties if p.get("city")})
    return {
        "found": True,
        "profile": {
            "name": profile.get("name"),
            "logo_url": profile.get("logo_url"),
            "about": profile.get("about"),
            "slug": profile["slug"],
        },
        "cities": cities,
        "rooms": rooms,
    }


class PublicBookRequest(BaseModel):
    listing_id: str
    guest_name: str
    guest_contact: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    nights: int = 1


@public_router.post("/{slug}/book")
async def public_book(slug: str, body: PublicBookRequest) -> dict[str, Any]:
    """Book a room directly (simulated payment), guarded against double-booking
    by the same atomic SELECT … FOR UPDATE the console uses."""
    profile = await _profile_by_slug(slug)
    if not profile or not profile.get("published"):
        raise HTTPException(status_code=404, detail="This hotel page is not available.")

    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    try:
        lid = uuid.UUID(body.listing_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad room id.") from None

    async with pool.acquire() as conn:
        listing = await conn.fetchrow(
            """SELECT l.id, l.title, l.price_amount, l.price_currency, l.capacity, l.org_id,
                      p.name AS property_name
               FROM supplier_listings l JOIN supplier_properties p ON p.id = l.property_id
               WHERE l.id = $1""",
            lid,
        )
    if not listing or str(listing["org_id"]) != profile["org_id"]:
        raise HTTPException(status_code=404, detail="Room not found.")

    org_id = str(listing["org_id"])
    capacity = int(listing["capacity"] or _DEFAULT_CAPACITY)
    currency = listing["price_currency"] or "MYR"
    nights = max(1, int(body.nights or 1))
    amount = float(listing["price_amount"] or 0) * nights
    channel = "journava-direct"

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO channel_inventory (listing_id, org_id, channel, allocated, sold) "
            "VALUES ($1,$2,$3,$4,0) ON CONFLICT (listing_id, channel) DO NOTHING",
            lid, uuid.UUID(org_id), channel, capacity,
        )
        async with conn.transaction():
            rows = await conn.fetch(
                "SELECT sold FROM channel_inventory WHERE listing_id = $1 FOR UPDATE", lid
            )
            total_sold = sum(int(r["sold"]) for r in rows)
            if total_sold >= capacity:
                return {"status": "blocked", "reason": "Sold out — that room was just taken. Try different dates."}
            await conn.execute(
                "UPDATE channel_inventory SET sold = sold + 1, updated_at = now() "
                "WHERE listing_id = $1 AND channel = $2",
                lid, channel,
            )
            payment_ref = "SIM-" + secrets.token_hex(5).upper()
            booking_id = await conn.fetchval(
                """INSERT INTO hotel_bookings
                       (org_id, listing_id, property_name, room_title, guest_name, guest_contact,
                        channel, check_in, check_out, nights, amount, currency,
                        status, payment_status, payment_ref)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'confirmed','paid',$13)
                   RETURNING id""",
                uuid.UUID(org_id), lid, listing["property_name"], listing["title"],
                body.guest_name, body.guest_contact, channel,
                date.fromisoformat(body.check_in) if body.check_in else None,
                date.fromisoformat(body.check_out) if body.check_out else None,
                nights, amount, currency, payment_ref,
            )

    # Ledger + notify (best-effort — never fail the guest's confirmation).
    try:
        from app.finance import record as finance_record

        await finance_record(
            org_id=org_id, kind="income", amount=amount, currency=currency,
            reference=str(booking_id), counterparty=body.guest_name,
            description=f"Direct booking · {listing['title']} · {nights} night(s)",
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("public book finance skipped: %s", exc)
    try:
        from app.tools import notify

        await notify.broadcast(
            f"🛎️ <b>Direct booking</b>\n{body.guest_name} booked <b>{listing['title']}</b> "
            f"({listing['property_name']}) — {currency} {amount:,.2f} for {nights} night(s). Paid {payment_ref}."
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("public book notify failed: %s", exc)

    return {
        "status": "confirmed",
        "booking_id": str(booking_id),
        "payment_ref": payment_ref,
        "amount": amount,
        "currency": currency,
        "nights": nights,
        "room": listing["title"],
        "property_name": listing["property_name"],
    }
