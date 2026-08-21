"""Agent-to-agent rate negotiation (the 'agentic infrastructure' headline).

The traveller's AI agent and the property's AI agent negotiate a room rate +
perks on their own, then the deal settles through the same rails as a normal
booking: firewall guard → booking → escrow hold → finance income → manager ping.

The outcome is computed deterministically (bounded by the supplier's floor and
the traveller's ceiling, so it always converges sanely and never sells below
cost), and a single LLM call narrates the back-and-forth for the demo.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core import db, llm
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/negotiate", tags=["negotiation"])

#: The supplier agent never goes below this fraction of the list price.
_FLOOR_FRACTION = 0.82


class NegotiateRequest(BaseModel):
    listing_id: str
    guest_name: str = "A guest"
    traveller_ceiling: float | None = None  # most the traveller will pay per night
    wants: str = ""                          # e.g. "late checkout, halal breakfast, sea view"
    nights: int = 1
    auto_book: bool = True


_NARRATE_SYSTEM = """You narrate a short, realistic negotiation between two AI \
agents: the GUEST's travel agent and the HOTEL's revenue agent. You are given the \
list price, the hidden floor, the guest's ceiling, the agreed price, and any perk. \
Produce 4-6 alternating turns that plausibly reach exactly that agreed price (and \
perk), each side professional and specific. If agreed is null, end in a polite \
no-deal.

Respond ONLY as JSON:
{"turns": [{"party": "guest_agent"|"hotel_agent", "message": "one sentence", "offer": number|null}]}"""


async def _narrate(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        raw = await llm.complete(
            [{"role": "system", "content": _NARRATE_SYSTEM}, {"role": "user", "content": json.dumps(ctx)}],
            response_format={"type": "json_object"}, agent="negotiation",
        )
        data = json.loads(raw)
        turns = data.get("turns") if isinstance(data, dict) else None
        if isinstance(turns, list) and turns:
            out = []
            for t in turns[:8]:
                if isinstance(t, dict) and t.get("message"):
                    out.append({
                        "party": "hotel_agent" if t.get("party") == "hotel_agent" else "guest_agent",
                        "message": str(t["message"]),
                        "offer": t.get("offer") if isinstance(t.get("offer"), (int, float)) else None,
                    })
            if out:
                return out
    except Exception as exc:  # noqa: BLE001
        logger.info("negotiation narrate fell back: %s", exc)
    # Deterministic fallback transcript.
    cur, lp, ag, perk = ctx["currency"], ctx["list_price"], ctx["agreed"], ctx.get("perk")
    if ag is None:
        return [
            {"party": "guest_agent", "message": f"My traveller's ceiling is {cur} {ctx['ceiling']:.0f}/night.", "offer": ctx["ceiling"]},
            {"party": "hotel_agent", "message": f"I can't go below {cur} {ctx['floor']:.0f} for this room — no deal this time.", "offer": ctx["floor"]},
        ]
    return [
        {"party": "guest_agent", "message": f"Listed at {cur} {lp:.0f}. My traveller can commit today at {cur} {ctx['ceiling']*0.9:.0f}.", "offer": round(ctx["ceiling"] * 0.9, 2)},
        {"party": "hotel_agent", "message": f"We hold rate at {cur} {lp:.0f}, but for a direct booking I can meet you partway.", "offer": lp},
        {"party": "guest_agent", "message": "Direct means no OTA fee for you — let's split the difference.", "offer": ag},
        {"party": "hotel_agent", "message": f"Agreed: {cur} {ag:.0f}/night" + (f", with {perk}." if perk else "."), "offer": ag},
    ]


async def _listing(listing_id: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT l.id, l.title, l.price_amount, l.price_currency, l.capacity, l.org_id,
                      p.name AS property_name
               FROM supplier_listings l JOIN supplier_properties p ON p.id = l.property_id
               WHERE l.id = $1""",
            uuid.UUID(listing_id),
        )
    return dict(row) if row else None


async def _book_deal(listing: dict[str, Any], guest: str, nightly: float, nights: int, perk: str | None) -> dict[str, Any]:
    """Settle an agreed deal on the normal rails: firewall guard → booking →
    escrow hold → finance income → manager ping."""
    from app.brain import escrow_store
    from app.finance import record as finance_record
    from app.tools import telegram

    pool = await db.get_pool()
    org_id = str(listing["org_id"])
    lid = listing["id"]
    capacity = int(listing["capacity"] or 10)
    currency = listing["price_currency"] or "MYR"
    amount = round(nightly * max(1, nights), 2)

    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO channel_inventory (listing_id, org_id, channel, allocated, sold)
               VALUES ($1,$2,'journava',$3,0) ON CONFLICT (listing_id, channel) DO NOTHING""",
            lid, listing["org_id"], capacity,
        )
        async with conn.transaction():
            rows = await conn.fetch("SELECT sold FROM channel_inventory WHERE listing_id = $1 FOR UPDATE", lid)
            if sum(int(r["sold"]) for r in rows) >= capacity:
                return {"status": "blocked", "reason": "Sold out — firewall blocked the deal."}
            await conn.execute(
                "UPDATE channel_inventory SET sold = sold + 1, updated_at = now() WHERE listing_id = $1 AND channel = 'journava'",
                lid,
            )
            booking_id = await conn.fetchval(
                """INSERT INTO hotel_bookings
                       (org_id, listing_id, property_name, room_title, guest_name, channel, check_in, check_out, nights, amount, currency)
                   VALUES ($1,$2,$3,$4,$5,'journava',current_date,current_date + ($6::int),$6,$7,$8) RETURNING id""",
                listing["org_id"], lid, listing["property_name"], listing["title"], guest,
                max(1, nights), amount, currency,
            )

    await escrow_store.open_hold(
        booking_ref=str(booking_id), amount=amount, currency=currency,
        description=f"Negotiated booking · {listing['title']}", org_id=org_id,
    )
    await finance_record(
        org_id=org_id, kind="income", amount=amount, currency=currency,
        reference=str(booking_id), counterparty=guest,
        description=f"Negotiated booking · {listing['title']}" + (f" · {perk}" if perk else ""),
    )
    try:
        await telegram.notify(
            f"🤝 <b>Agent-negotiated booking</b>\n{guest} — {listing['title']} at "
            f"{currency} {nightly:,.0f}/night" + (f" (+{perk})" if perk else "") + f", {nights} night(s)."
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("negotiation notify failed: %s", exc)
    return {"status": "confirmed", "booking_id": str(booking_id), "amount": amount, "currency": currency}


@router.post("")
async def negotiate(body: NegotiateRequest, request: Request) -> dict[str, Any]:
    """Run a guest-agent ↔ hotel-agent negotiation and (optionally) book the deal."""
    listing = await _listing(body.listing_id)
    if not listing:
        return {"error": "Listing not found."}
    list_price = float(listing["price_amount"]) if listing["price_amount"] is not None else 0.0
    currency = listing["price_currency"] or "MYR"
    if list_price <= 0:
        return {"error": "This room has no price to negotiate."}

    floor = round(list_price * _FLOOR_FRACTION, 2)
    ceiling = round(body.traveller_ceiling if body.traveller_ceiling else list_price * 0.95, 2)

    agreed: float | None = None
    perk: str | None = None
    if ceiling >= floor:
        agreed = round(max(floor, min((floor + min(ceiling, list_price)) / 2, ceiling)), 2)
        perk = "late checkout + halal breakfast" if agreed >= list_price * 0.9 else "late checkout"
    savings = round(list_price - agreed, 2) if agreed is not None else 0.0

    transcript = await _narrate({
        "currency": currency, "list_price": list_price, "floor": floor, "ceiling": ceiling,
        "agreed": agreed, "perk": perk, "wants": body.wants, "guest": body.guest_name,
    })

    deal = {
        "agreed": agreed is not None,
        "list_price": list_price,
        "price": agreed,
        "currency": currency,
        "perk": perk,
        "savings": savings,
        "room": listing["title"],
        "property": listing["property_name"],
    }
    booking = None
    if agreed is not None and body.auto_book:
        booking = await _book_deal(listing, body.guest_name, agreed, body.nights, perk)

    return {"deal": deal, "transcript": transcript, "booking": booking}
