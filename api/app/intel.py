"""Predictive Travel Intelligence — the "book now or wait?" agent.

Fills the Data & Analytics track (hackathon direction 06) with a genuinely
forward-looking, agentic insight: it synthesises the signals the mesh already
gathered — the live fare spread, crowd level, weather risk, season and dates —
into a recommendation to BOOK NOW or WAIT, a best-book-by deadline, a price
outlook and a demand forecast. Predictive, grounded, and honest about
confidence — not a generic tip.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.brain import trip_store
from app.core import llm
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/intel", tags=["intel"])


class PredictRequest(BaseModel):
    # Optional: analyse a plan-in-progress from the results page; otherwise the
    # active trip is used.
    results: dict[str, Any] | None = None


_SYSTEM = """You are Journava's Travel Intelligence agent. Given a trip's LIVE \
signals, predict whether the traveller should BOOK NOW or WAIT — and when. \
Ground every claim in the provided signals plus seasonal/route knowledge, and be \
honest about confidence (say "low" when the signal is thin). Never invent a \
specific price.

Respond ONLY as JSON:
{"verdict": "book_now" | "wait" | "flexible",
 "confidence": "high" | "medium" | "low",
 "price_trend": "rising" | "stable" | "falling",
 "book_by": "plain-English deadline, e.g. 'within ~5 days'",
 "demand": "low" | "moderate" | "high",
 "reason": "1-2 sentences citing the actual signals",
 "cheaper_window": "a cheaper period if the dates look flexible, else null",
 "savings_hint": "one concrete lever, e.g. 'flying midweek could save ~15%', or null"}"""


def _signals(res: dict[str, Any]) -> dict[str, Any]:
    """Pull the forward-looking signals out of a plan/trip snapshot."""
    chief = (res.get("chief") or {}).get("data") or {}
    flight = res.get("flight") or {}
    fopts = flight.get("options") or []
    prices = [float(o["price_amount"]) for o in fopts if o.get("price_amount") is not None]
    crowd = (res.get("crowd") or {}).get("data") or {}
    weather = (res.get("weather_risk") or {}).get("data") or {}
    currency = next((o.get("price_currency") for o in fopts if o.get("price_currency")), None)
    return {
        "destination": chief.get("destination"),
        "origin": chief.get("origin"),
        "start_date": chief.get("start_date"),
        "end_date": chief.get("end_date"),
        "travellers": chief.get("travellers"),
        "fare_low": round(min(prices)) if prices else None,
        "fare_high": round(max(prices)) if prices else None,
        "fare_currency": currency,
        "flight_options": len(fopts),
        "bookable_now": sum(1 for o in fopts if o.get("bookable")),
        "crowd_level": crowd.get("crowd_level"),
        "avoid_periods": crowd.get("avoid_periods"),
        "best_week": crowd.get("best_week"),
        "weather_risk": weather.get("risk_level"),
    }


@router.post("/predict")
async def predict(body: PredictRequest, request: Request) -> dict[str, Any]:
    """Return a book-now-or-wait prediction for the plan/active trip."""
    res = body.results or (await trip_store.load_trip_durable() or {})
    if not res:
        return {"error": "No trip to analyse yet."}
    signals = _signals(res)
    if not signals.get("destination"):
        return {"error": "Not enough signal to predict yet."}

    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": json.dumps(signals, default=str)},
            ],
            response_format={"type": "json_object"},
            agent="analytics",
        )
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError("intel not an object")
    except Exception as exc:  # noqa: BLE001 — a missing prediction never breaks a plan
        logger.info("intel predict failed: %s", exc)
        return {"error": "Travel Intelligence is unavailable right now."}

    data["signals"] = signals
    return {"intel": data}
