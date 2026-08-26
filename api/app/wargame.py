"""Disruption War Room — a strategic what-if simulator for the business.

Where Trip Operations recovers a single traveller's broken itinerary, the War
Room plays out a *business* shock against the org's real numbers (live rooms,
average rate, bookings, revenue): a competitor price war, an OTA delisting, a
weather event, a demand surge, a partner failure. An adversarial agent makes the
opening move; a strategist agent games the impact and returns response options,
the likely counter-move, and the recommended play — grounded in the org's data.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import require_agency
from app.core import db, llm
from app.core.settings import settings
from app.supplier import store as supplier_store
from app.tools import discover

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/wargame", tags=["wargame"])

SCENARIOS = [
    {"id": "price_war", "label": "Competitor price war", "icon": "trend",
     "prompt": "A well-reviewed hotel two streets away just cut its nightly rates ~30% for the whole season and is advertising it hard."},
    {"id": "ota_delist", "label": "OTA delists us", "icon": "shield",
     "prompt": "Our single biggest OTA channel has delisted us over a dispute; those bookings stop within 48 hours."},
    {"id": "weather", "label": "Weather / flight shock", "icon": "cloud",
     "prompt": "A monsoon / storm warning is cancelling most inbound flights to our city for the next 10 days."},
    {"id": "demand_surge", "label": "Sudden demand surge", "icon": "zap",
     "prompt": "A major festival / conference was just announced in our city next month — demand is about to spike well above supply."},
    {"id": "partner_fail", "label": "Key partner fails", "icon": "alert",
     "prompt": "Our main transport / tours partner just went out of business mid-season, breaking packages we already sold."},
]

_SYSTEM = """You are a hotel/agency revenue & strategy war-gamer. Given a \
disruption scenario and the business's REAL numbers, play it out honestly and \
concretely. Think like an operator: protect revenue and occupancy, use the \
levers a small hotel actually has (price, packaging, direct channel, partners, \
comms). Reference the real numbers where relevant.

Respond ONLY as JSON:
{"situation": "1-2 sentence framing of what's happening and why it matters",
 "impact": {"revenue_at_risk_pct": number 0-100, "summary": "1 sentence on the hit if we do nothing"},
 "options": [{"name": "short label", "description": "what we do", "projected_outcome": "likely result", "effort": "low|medium|high"} ...exactly 3, best first],
 "red_team": "the competitor's or market's most likely counter-move to our best option",
 "our_counter": "how we answer that counter-move",
 "recommended": "1-2 sentences: the play to run now and why"}"""


class RunRequest(BaseModel):
    scenario_id: str | None = None
    custom: str | None = None


async def _org_stats(org_id: str) -> dict[str, Any]:
    properties = await supplier_store.list_properties(org_id)
    rooms = [l for p in properties for l in (p.get("listings") or [])]
    prices = [float(l["price_amount"]) for l in rooms if l.get("price_amount")]
    cities = sorted({(p.get("city") or "").strip() for p in properties if p.get("city")})
    avg_price = round(sum(prices) / len(prices)) if prices else None
    bookings = revenue = 0
    currency = "MYR"
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT count(*) AS n, COALESCE(SUM(amount),0) AS rev, MAX(currency) AS cur "
                    "FROM hotel_bookings WHERE org_id = $1 AND status <> 'cancelled'",
                    uuid.UUID(org_id),
                )
            bookings = int(row["n"] or 0)
            revenue = round(float(row["rev"] or 0))
            currency = row["cur"] or "MYR"
        except Exception as exc:  # noqa: BLE001
            logger.info("wargame stats skipped: %s", exc)
    return {
        "live_rooms": len(rooms), "avg_nightly_rate": avg_price, "currency": currency,
        "cities": cities, "bookings": bookings, "booked_revenue": revenue,
    }


@router.get("/scenarios")
async def scenarios(_: dict = Depends(require_agency)) -> dict[str, Any]:
    return {"scenarios": [{"id": s["id"], "label": s["label"], "icon": s["icon"]} for s in SCENARIOS]}


@router.post("/run")
async def run(body: RunRequest, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    org_id = agency["org_id"]
    preset = next((s for s in SCENARIOS if s["id"] == body.scenario_id), None)
    scenario_text = (body.custom or "").strip() or (preset["prompt"] if preset else "")
    if not scenario_text:
        return {"error": "Pick a scenario or describe one."}

    stats = await _org_stats(org_id)
    # A little live market colour for the city (best-effort), so the war-game is
    # grounded in the real world rather than pure imagination.
    market = ""
    if stats["cities"]:
        try:
            res = await discover.crawl_sources([f"{stats['cities'][0]} hotel demand travel news this month"])
            market = (res or {}).get("text", "")[:1400]
        except Exception as exc:  # noqa: BLE001
            logger.info("wargame market crawl skipped: %s", exc)

    org_name = agency.get("org_name") or "our business"
    user = (
        f"Business: {org_name}. Real numbers: {stats['live_rooms']} live rooms, "
        f"avg nightly rate {stats['currency']} {stats['avg_nightly_rate']}, "
        f"{stats['bookings']} active bookings worth {stats['currency']} {stats['booked_revenue']}, "
        f"cities: {', '.join(stats['cities']) or 'n/a'}.\n\n"
        f"DISRUPTION SCENARIO:\n{scenario_text}\n\n"
        f"Live market context (may be empty):\n{market or '(none)'}"
    )
    result: dict[str, Any] = {
        "situation": scenario_text,
        "impact": {"revenue_at_risk_pct": 0, "summary": ""},
        "options": [], "red_team": "", "our_counter": "", "recommended": "",
    }
    try:
        raw = await llm.complete(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            response_format={"type": "json_object"}, agent="supplier",
        )
        data = json.loads(raw)
        if isinstance(data, dict):
            for k in result:
                if data.get(k) is not None:
                    result[k] = data[k]
            result["options"] = (data.get("options") or [])[:3]
    except Exception as exc:  # noqa: BLE001
        logger.info("wargame fell back: %s", exc)
        result["recommended"] = "The strategist is unavailable right now — try again in a moment."

    result["scenario_label"] = preset["label"] if preset else "Custom scenario"
    result["stats"] = stats
    return result
