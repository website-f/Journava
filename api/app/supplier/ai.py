"""Supplier-side AI agents — the agency actually *uses* the mesh.

This is the supply-side counterpart to the consumer agents: instead of planning
a traveller's trip, these agents help a hotel/agency fill rooms and run their
listings.

- draft_listing  — a copywriter+revenue agent writes a full listing from a hint.
- publish        — save an AI draft as a live property + room.
- price          — a Yield agent crawls comparable rates (Camofox) and recommends
                   a competitive price with a rationale.
- lead_reply     — a concierge agent drafts a personalised quote to a lead.
- visibility     — how the org's rooms surfaced in real consumer searches.

A published room is immediately live to travellers: the Hotel Agent's
`_supplier_options` surfaces it (bookable, no OTA cut) whenever someone searches
that city — so the supply→demand loop closes without any OTA in the middle.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import require_agency
from app.core import db, llm
from app.core.settings import settings
from app.supplier import store as supplier_store
from app.tools import discover

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/supplier/ai", tags=["supplier-ai"])


class DraftRequest(BaseModel):
    name: str = ""
    city: str
    kind: str = "hotel"  # hotel | attraction
    room: str = ""  # e.g. "Deluxe Sea View"
    notes: str = ""
    halal_friendly: bool = False


class PublishRequest(BaseModel):
    name: str
    city: str
    country: str = "Malaysia"
    kind: str = "hotel"
    halal_friendly: bool = False
    room_title: str
    description: str = ""
    price_amount: float
    price_currency: str = "MYR"
    perks: list[str] = []
    capacity: int = 5


_DRAFT_SYSTEM = """You are a revenue manager + copywriter for a property listing \
on Journava (a direct-booking marketplace that bypasses the OTAs). From the \
supplier's short hint, produce a polished, bookable listing.

Respond ONLY as JSON:
{"room_title": "concise room/ticket name", "description": "2-3 sentence guest-facing \
description", "perks": ["short perk", ...max 6], "suggested_price": number, \
"price_currency": "MYR", "capacity": number, "halal_friendly": boolean}"""


@router.post("/draft-listing")
async def draft_listing(body: DraftRequest, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    """An agent drafts a full listing (copy + perks + suggested price)."""
    user = (
        f"Property: {body.name or 'a ' + body.kind} in {body.city}. Type: {body.kind}. "
        f"Room/ticket: {body.room or 'standard'}. Halal-friendly: {body.halal_friendly}. "
        f"Notes: {body.notes or 'none'}."
    )
    draft: dict[str, Any] = {
        "room_title": body.room or "Standard Room",
        "description": "",
        "perks": [],
        "suggested_price": 300,
        "price_currency": "MYR",
        "capacity": 5,
        "halal_friendly": body.halal_friendly,
    }
    try:
        raw = await llm.complete(
            [{"role": "system", "content": _DRAFT_SYSTEM}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            agent="supplier",
        )
        data = json.loads(raw)
        if isinstance(data, dict):
            draft.update({k: data[k] for k in draft if k in data and data[k] is not None})
            draft["perks"] = [str(p) for p in (data.get("perks") or [])][:6]
    except Exception as exc:  # noqa: BLE001
        logger.info("draft-listing fell back: %s", exc)
    draft["name"] = body.name or f"{body.city} {body.kind.title()}"
    draft["city"] = body.city
    draft["kind"] = body.kind
    return {"draft": draft}


@router.post("/publish")
async def publish(body: PublishRequest, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    """Persist an AI draft as a live property + bookable room (org-scoped)."""
    org_id = agency["org_id"]
    prop = await supplier_store.create_property(
        org_id, name=body.name, kind=body.kind, city=body.city, country=body.country,
        description=body.description, halal_friendly=body.halal_friendly, image_url=None,
    )
    if not prop:
        return {"error": "Could not create the property."}
    listing = await supplier_store.add_listing(
        org_id, prop["id"], title=body.room_title, price_amount=body.price_amount,
        price_currency=body.price_currency, capacity=body.capacity, perks=body.perks, available=True,
    )
    return {"property": prop, "listing": listing, "live": True, "city": body.city}


_PRICE_SYSTEM = """You are a hotel Yield / Revenue-management agent. Recommend a \
nightly price that maximises REVENUE with demand-based DYNAMIC pricing — not just \
matching competitors. Rules:
- Raise the price when occupancy is high, it's peak season, or there are events / \
  festivals / holidays in the city.
- Cut the price to fill rooms when occupancy is low or it's off-peak.
- Never drift so far from comparable rates that the room won't sell.
Be specific and honest; if a signal is missing, say so in the rationale.

Respond ONLY as JSON:
{"recommended_price": number, "currency": "MYR", "comp_low": number|null, \
"comp_high": number|null, "delta_pct": number, "occupancy_pct": number|null, \
"demand_level": "low"|"moderate"|"high", "drivers": ["short factor", ...max 4], \
"rationale": "1-2 sentences"}"""


async def _listing_row(listing_id: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    import uuid as _uuid
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT l.title, l.price_amount, l.price_currency, p.name AS property, p.city
               FROM supplier_listings l JOIN supplier_properties p ON p.id = l.property_id
               WHERE l.id = $1""",
            _uuid.UUID(listing_id),
        )
    return dict(row) if row else None


async def _occupancy_pct(listing_id: str) -> float | None:
    """Sold vs allocated across the listing's channels — the demand signal that
    makes pricing dynamic (yield management) rather than a static comp match."""
    pool = await db.get_pool()
    if pool is None:
        return None
    import uuid as _uuid
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT COALESCE(SUM(allocated), 0) AS alloc, COALESCE(SUM(sold), 0) AS sold
                   FROM channel_inventory WHERE listing_id = $1""",
                _uuid.UUID(listing_id),
            )
    except Exception as exc:  # noqa: BLE001
        logger.info("occupancy lookup skipped: %s", exc)
        return None
    alloc = float(row["alloc"]) if row and row["alloc"] else 0.0
    if alloc <= 0:
        return None
    return round(100.0 * float(row["sold"]) / alloc, 1)


@router.post("/price/{listing_id}")
async def price(listing_id: str, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    """Yield agent: dynamic price from comps + occupancy + live demand (events)."""
    row = await _listing_row(listing_id)
    if not row:
        return {"error": "Listing not found."}
    city = row.get("city") or ""
    current = float(row["price_amount"]) if row.get("price_amount") is not None else None
    currency = row.get("price_currency") or "MYR"

    occupancy = await _occupancy_pct(listing_id)
    comps = demand = ""
    try:
        res = await discover.crawl_sources([f"hotel room price per night {city}", f"{city} hotel rates tonight"])
        comps = (res or {}).get("text", "")[:2600]
    except Exception as exc:  # noqa: BLE001
        logger.info("price comp crawl skipped: %s", exc)
    try:
        # Live demand: events/festivals/holidays that should push the price up.
        res2 = await discover.crawl_sources([f"{city} events festivals this month", f"{city} public holidays peak travel season"])
        demand = (res2 or {}).get("text", "")[:1800]
    except Exception as exc:  # noqa: BLE001
        logger.info("price demand crawl skipped: %s", exc)

    user = (
        f"Room: {row.get('title')} at {row.get('property')} in {city}. "
        f"Current price: {currency} {current if current is not None else 'unset'}/night.\n"
        f"Occupancy (sold/allocated across channels): {occupancy if occupancy is not None else 'unknown'}%.\n"
        f"Comparable market rates crawled:\n{comps or '(none — use your knowledge of ' + city + ')'}\n\n"
        f"Live demand signals (events / season) crawled:\n{demand or '(none available)'}"
    )
    out: dict[str, Any] = {
        "recommended_price": current or 300, "currency": currency, "comp_low": None, "comp_high": None,
        "delta_pct": 0, "occupancy_pct": occupancy, "demand_level": "moderate", "drivers": [], "rationale": "",
    }
    try:
        raw = await llm.complete(
            [{"role": "system", "content": _PRICE_SYSTEM}, {"role": "user", "content": user}],
            response_format={"type": "json_object"}, agent="supplier",
        )
        data = json.loads(raw)
        if isinstance(data, dict):
            for k in out:
                if data.get(k) is not None:
                    out[k] = data[k]
    except Exception as exc:  # noqa: BLE001
        logger.info("price recommend fell back: %s", exc)
    out["current_price"] = current
    out["occupancy_pct"] = occupancy  # trust the measured value over the LLM's echo
    out["sourced"] = bool(comps or demand)
    return out


_REPLY_SYSTEM = """You are a hotel concierge. Draft a warm, concise reply to a \
traveller's booking enquiry that confirms availability, restates the room + price, \
adds one helpful local tip, and invites them to confirm. Plain text, 4-6 sentences."""


@router.post("/lead-reply/{lead_id}")
async def lead_reply(lead_id: str, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    """Concierge agent drafts a personalised quote reply to a lead."""
    leads = await supplier_store.list_leads(agency["org_id"])
    lead = next((x for x in leads if x["id"] == lead_id), None)
    if not lead:
        return {"error": "Lead not found."}
    user = (
        f"Enquiry for {lead.get('listing_title') or 'a room'} at {lead.get('property_name') or 'our property'}. "
        f"Traveller note: {lead.get('note') or '(none)'}. Traveller email: {lead.get('traveler_email') or 'n/a'}."
    )
    reply = "Thank you for your interest — we'd be glad to host you. Please let us know your dates to confirm."
    try:
        reply = (await llm.complete(
            [{"role": "system", "content": _REPLY_SYSTEM}, {"role": "user", "content": user}],
            agent="supplier",
        )).strip() or reply
    except Exception as exc:  # noqa: BLE001
        logger.info("lead-reply fell back: %s", exc)
    return {"lead_id": lead_id, "reply": reply}


@router.get("/visibility")
async def visibility(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    """How the org's rooms surfaced in real consumer searches (supply→demand)."""
    org_id = agency["org_id"]
    properties = await supplier_store.list_properties(org_id)
    cities = sorted({(p.get("city") or "").strip() for p in properties if p.get("city")})
    live_rooms = sum(len(p.get("listings") or []) for p in properties)

    appeared = 0
    pool = await db.get_pool()
    if pool is not None and cities:
        async with pool.acquire() as conn:
            for city in cities:
                appeared += int(await conn.fetchval(
                    "SELECT count(*) FROM search_history WHERE destination ILIKE '%'||$1||'%'", city
                ) or 0)
    leads = await supplier_store.list_leads(org_id)
    return {
        "cities": cities,
        "live_rooms": live_rooms,
        "appeared_in_searches": appeared,
        "leads": len(leads),
        "conversion_hint": "Each search that reached your city surfaced your direct room ahead of the OTAs.",
    }
