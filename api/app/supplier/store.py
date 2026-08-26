"""Supplier data access — properties, listings, leads. All org-scoped.

Degrades to empty/None when Postgres is down, like the rest of the app.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core import db

logger = logging.getLogger(__name__)


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


_LISTING_COLS = (
    "id, property_id, title, price_amount, price_currency, capacity, perks, available, "
    "description, image_url, original_price, discount_pct, amenities"
)
_PROPERTY_COLS = (
    "id, org_id, name, kind, city, country, description, halal_friendly, image_url, "
    "amenities, star_rating"
)


def _listing(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "property_id": str(row["property_id"]),
        "title": row["title"],
        "price_amount": float(row["price_amount"]) if row.get("price_amount") is not None else None,
        "price_currency": row["price_currency"],
        "capacity": row.get("capacity"),
        "perks": list(row.get("perks") or []),
        "available": row["available"],
        "description": row.get("description"),
        "image_url": row.get("image_url"),
        "original_price": float(row["original_price"]) if row.get("original_price") is not None else None,
        "discount_pct": row.get("discount_pct"),
        "amenities": list(row.get("amenities") or []),
    }


def _property(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "kind": row["kind"],
        "city": row["city"],
        "country": row.get("country"),
        "description": row.get("description"),
        "halal_friendly": row["halal_friendly"],
        "image_url": row.get("image_url"),
        "amenities": list(row.get("amenities") or []),
        "star_rating": row.get("star_rating"),
    }


# --------------------------------------------------------------------------- #
# Properties + listings (supplier-owned, org-scoped)
# --------------------------------------------------------------------------- #


async def create_property(org_id: str, **fields: Any) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""INSERT INTO supplier_properties
                   (org_id, name, kind, city, country, description, halal_friendly,
                    image_url, amenities, star_rating)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               RETURNING {_PROPERTY_COLS}""",  # noqa: S608 — fixed columns
            _uuid(org_id),
            fields["name"],
            fields.get("kind", "hotel"),
            fields["city"],
            fields.get("country"),
            fields.get("description"),
            bool(fields.get("halal_friendly", False)),
            fields.get("image_url"),
            list(fields.get("amenities") or []),
            fields.get("star_rating"),
        )
    return _property(dict(row)) if row else None


async def list_properties(org_id: str) -> list[dict[str, Any]]:
    """The org's properties, each with its listings nested."""
    pool = await db.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        props = await conn.fetch(
            f"SELECT {_PROPERTY_COLS} FROM supplier_properties WHERE org_id = $1 ORDER BY created_at DESC",  # noqa: S608
            _uuid(org_id),
        )
        listings = await conn.fetch(
            f"SELECT {_LISTING_COLS} FROM supplier_listings WHERE org_id = $1 ORDER BY created_at",  # noqa: S608
            _uuid(org_id),
        )
    by_prop: dict[str, list[dict[str, Any]]] = {}
    for row in listings:
        item = _listing(dict(row))
        by_prop.setdefault(item["property_id"], []).append(item)
    out = []
    for row in props:
        prop = _property(dict(row))
        prop["listings"] = by_prop.get(prop["id"], [])
        out.append(prop)
    return out


async def owns_property(org_id: str, property_id: str) -> bool:
    pool = await db.get_pool()
    if pool is None:
        return False
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM supplier_properties WHERE id = $1 AND org_id = $2",
            _uuid(property_id),
            _uuid(org_id),
        )
    return row is not None


async def delete_property(org_id: str, property_id: str) -> bool:
    pool = await db.get_pool()
    if pool is None:
        return False
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM supplier_properties WHERE id = $1 AND org_id = $2",
            _uuid(property_id),
            _uuid(org_id),
        )
    return result.endswith("1")


async def add_listing(org_id: str, property_id: str, **fields: Any) -> dict[str, Any] | None:
    if not await owns_property(org_id, property_id):
        return None
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""INSERT INTO supplier_listings
                   (property_id, org_id, title, price_amount, price_currency, capacity,
                    perks, available, description, image_url, original_price, discount_pct, amenities)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               RETURNING {_LISTING_COLS}""",  # noqa: S608 — fixed columns
            _uuid(property_id),
            _uuid(org_id),
            fields["title"],
            fields.get("price_amount"),
            fields.get("price_currency", "MYR"),
            fields.get("capacity"),
            list(fields.get("perks") or []),
            bool(fields.get("available", True)),
            fields.get("description"),
            fields.get("image_url"),
            fields.get("original_price"),
            fields.get("discount_pct"),
            list(fields.get("amenities") or []),
        )
    return _listing(dict(row)) if row else None


async def delete_listing(org_id: str, listing_id: str) -> bool:
    pool = await db.get_pool()
    if pool is None:
        return False
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM supplier_listings WHERE id = $1 AND org_id = $2",
            _uuid(listing_id),
            _uuid(org_id),
        )
    return result.endswith("1")


# --------------------------------------------------------------------------- #
# Traveler-facing search (used by the Hotel Agent) — NOT org-scoped
# --------------------------------------------------------------------------- #


async def search_for_destination(destination: str) -> list[dict[str, Any]]:
    """Available direct listings whose property matches the destination.

    Matches loosely both ways ("Kota Kinabalu" ~ "kota kinabalu" ~ a substring)
    so a natural destination string finds a supplier without exact spelling.
    """
    pool = await db.get_pool()
    if pool is None or not destination:
        return []
    term = destination.strip()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT l.id, l.title, l.price_amount, l.price_currency, l.perks,
                      p.id AS property_id, p.org_id, p.name AS property_name,
                      p.city, p.halal_friendly
               FROM supplier_listings l
               JOIN supplier_properties p ON p.id = l.property_id
               WHERE l.available = TRUE
                 AND (p.city ILIKE '%'||$1||'%'
                      OR $1 ILIKE '%'||p.city||'%'
                      OR p.name ILIKE '%'||$1||'%')
               ORDER BY l.price_amount NULLS LAST
               LIMIT 12""",
            term,
        )
    out: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        out.append(
            {
                "listing_id": str(r["id"]),
                "property_id": str(r["property_id"]),
                "org_id": str(r["org_id"]),
                "property_name": r["property_name"],
                "title": r["title"],
                "price_amount": float(r["price_amount"]) if r.get("price_amount") is not None else None,
                "price_currency": r["price_currency"],
                "perks": list(r.get("perks") or []),
                "halal_friendly": r["halal_friendly"],
                "city": r["city"],
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Leads
# --------------------------------------------------------------------------- #


async def listing_context(listing_id: str) -> dict[str, str] | None:
    """The org + property a listing belongs to — so a traveler lead routes to the
    right supplier without the traveler needing to know the org."""
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT org_id, property_id FROM supplier_listings WHERE id = $1",
            _uuid(listing_id),
        )
    if not row:
        return None
    return {"org_id": str(row["org_id"]), "property_id": str(row["property_id"])}


async def create_lead(
    *,
    org_id: str,
    property_id: str | None,
    listing_id: str | None,
    traveler_user_id: str | None,
    traveler_email: str | None,
    note: str | None,
) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO supplier_leads
                   (org_id, property_id, listing_id, traveler_user_id, traveler_email, note)
               VALUES ($1,$2,$3,$4,$5,$6)
               RETURNING id, status, created_at""",
            _uuid(org_id),
            _uuid(property_id) if property_id else None,
            _uuid(listing_id) if listing_id else None,
            _uuid(traveler_user_id) if traveler_user_id else None,
            traveler_email,
            note,
        )
    return {"id": str(row["id"]), "status": row["status"]} if row else None


async def list_leads(org_id: str) -> list[dict[str, Any]]:
    pool = await db.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ll.id, ll.status, ll.note, ll.traveler_email, ll.created_at,
                      p.name AS property_name, l.title AS listing_title
               FROM supplier_leads ll
               LEFT JOIN supplier_properties p ON p.id = ll.property_id
               LEFT JOIN supplier_listings l ON l.id = ll.listing_id
               WHERE ll.org_id = $1 ORDER BY ll.created_at DESC LIMIT 100""",
            _uuid(org_id),
        )
    return [
        {
            "id": str(r["id"]),
            "status": r["status"],
            "note": r["note"],
            "traveler_email": r["traveler_email"],
            "property_name": r["property_name"],
            "listing_title": r["listing_title"],
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        }
        for r in (dict(x) for x in rows)
    ]


async def summary(org_id: str) -> dict[str, int]:
    pool = await db.get_pool()
    if pool is None:
        return {"properties": 0, "listings": 0, "leads": 0, "new_leads": 0}
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT
                 (SELECT count(*) FROM supplier_properties WHERE org_id = $1) AS properties,
                 (SELECT count(*) FROM supplier_listings   WHERE org_id = $1) AS listings,
                 (SELECT count(*) FROM supplier_leads      WHERE org_id = $1) AS leads,
                 (SELECT count(*) FROM supplier_leads      WHERE org_id = $1 AND status='new') AS new_leads""",
            _uuid(org_id),
        )
    return {k: int(row[k]) for k in ("properties", "listings", "leads", "new_leads")}
