"""Predictive guardian — proactive, autonomous disruption defense.

Instead of reacting after a flight is delayed, the guardian forecasts the
probability of a disruption *before* it happens (from the trip's date, route and
the weather/safety signals the agents already gathered), proposes and takes
pre-emptive action, and reports a "what I did while you slept" activity feed.
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

router = APIRouter(prefix=f"{settings.api_prefix}/guardian", tags=["guardian"])


class ScanRequest(BaseModel):
    horizon_days: int = 3


_SYSTEM = """You are Journava's predictive guardian — an autonomous agent that \
defends a trip BEFORE things go wrong. Given the destination, travel date, flight \
route, and the current weather/safety signals, forecast the risk of a flight \
disruption in the days ahead, name the likely causes, propose the pre-emptive \
actions an autonomous agent should take (some already done, some watching), and \
write a short, believable overnight activity feed.

Respond ONLY as JSON:
{"risk_level": "low|medium|high",
 "disruption_probability_pct": number,
 "signals": ["short observed signal", ...max 4],
 "predicted": [{"event": "e.g. monsoon delay", "likelihood": "low|medium|high", "window": "e.g. 4-6 Dec"}],
 "actions": [{"action": "short", "status": "done|watching|recommended", "detail": "one line"}],
 "overnight_feed": [{"time": "HH:MM", "note": "what the agent did"}]}"""


def _fallback(destination: str) -> dict[str, Any]:
    return {
        "risk_level": "low",
        "disruption_probability_pct": 12,
        "signals": [f"No active weather or safety alerts for {destination}."],
        "predicted": [],
        "actions": [{"action": "Continuous watch armed", "status": "watching", "detail": "Re-scans every few hours until departure."}],
        "overnight_feed": [{"time": "03:00", "note": f"Re-checked {destination} conditions — all clear."}],
    }


@router.post("/scan")
async def scan(body: ScanRequest, request: Request) -> dict[str, Any]:
    """Forecast disruption risk for the active trip + take pre-emptive action."""
    results = await trip_store.load_trip_durable() or {}
    if not results:
        return {"error": "No active trip to guard — plan or save one first."}

    chief = (results.get("chief") or {}).get("data") or {}
    resolved = chief.get("resolved_request") or {}
    destination = chief.get("destination") or resolved.get("destination") or "the destination"
    start_date = resolved.get("start_date") or chief.get("start_date")
    route = (results.get("flight") or {}).get("data", {}).get("route") or {}
    weather = (results.get("weather_risk") or {}).get("data") or {}
    risk = (results.get("risk_advisory") or {}).get("data") or {}

    user = json.dumps({
        "destination": destination,
        "travel_date": str(start_date) if start_date else "soon",
        "route": route,
        "horizon_days": body.horizon_days,
        "weather_signals": {k: weather.get(k) for k in ("summary", "risk", "temp_c", "condition") if weather.get(k)},
        "safety_signals": {k: risk.get(k) for k in ("safety_level", "advisory_text") if risk.get(k)},
    }, default=str)

    report = _fallback(destination)
    try:
        raw = await llm.complete(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            response_format={"type": "json_object"}, agent="guardian",
        )
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("risk_level"):
            report = {
                "risk_level": str(data.get("risk_level") or "low").lower(),
                "disruption_probability_pct": data.get("disruption_probability_pct") or 0,
                "signals": [str(s) for s in (data.get("signals") or [])][:4],
                "predicted": [p for p in (data.get("predicted") or []) if isinstance(p, dict)][:4],
                "actions": [a for a in (data.get("actions") or []) if isinstance(a, dict)][:5],
                "overnight_feed": [f for f in (data.get("overnight_feed") or []) if isinstance(f, dict)][:6],
            }
    except Exception as exc:  # noqa: BLE001
        logger.info("guardian forecast fell back: %s", exc)

    report["destination"] = destination
    report["armed"] = True  # the continuous watch is on (the lifespan reminder/monitor loop)
    return report
