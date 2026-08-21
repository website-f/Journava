"""Agency / partner console — the B2B surface.

Aggregates the org's managed trips and the OTA commission avoided by booking
direct through Journava's agents. This is the "bypass the OTAs" story: an agency
(or a hotel via the Partner portal) lets the agent mesh search, book and monitor
directly, keeping the ~10% an OTA would take.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from app.auth.deps import resolve_org_id
from app.brain import history, policy_store
from app.core.settings import settings
from app.tools import policy as policy_tools

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/agency", tags=["agency"])


@router.get("/overview")
async def overview(request: Request, limit: int = 15) -> dict[str, Any]:
    """Managed trips + aggregate OTA commission avoided (from flight results)."""
    entries = await history.list_entries(limit=limit)
    trips: list[dict[str, Any]] = []
    total_saved = 0.0
    currency = "MYR"

    for entry in entries:
        saved = 0.0
        try:
            full = await history.get_entry(entry["id"])
            snapshot = (full or {}).get("result_snapshot") or {}
            flight = snapshot.get("flight") or {}
            saved_info = (flight.get("data") or {}).get("commission_saved") or {}
            saved = float(saved_info.get("amount") or 0)
            if saved_info.get("currency"):
                currency = saved_info["currency"]
        except Exception:  # noqa: BLE001 — a bad snapshot must not break the console
            saved = 0.0
        total_saved += saved
        trips.append(
            {
                "id": entry["id"],
                "goal": entry.get("goal"),
                "scope": entry.get("scope"),
                "destination": entry.get("destination"),
                "option_count": entry.get("option_count", 0),
                "created_at": entry.get("created_at"),
                "saved": round(saved, 2),
            }
        )

    return {
        "metrics": {
            "managed_trips": len(trips),
            "total_saved": round(total_saved, 2),
            "currency": currency,
            "commission_rate_pct": 10,
        },
        "trips": trips,
    }


@router.get("/corporate")
async def corporate(request: Request, limit: int = 25) -> dict[str, Any]:
    """Corporate control tower: active policy + compliance, duty-of-care (where
    are our travellers and how risky), and ESG (aggregate carbon)."""
    org_id = await resolve_org_id(request)
    policy_doc = policy_tools.merge(await policy_store.load_policy(org_id))

    entries = await history.list_entries(limit=limit)
    travellers: list[dict[str, Any]] = []
    risk_counts = {"safe": 0, "caution": 0, "dangerous": 0}
    esg = {"total_co2_kg": 0.0, "total_offset_usd": 0.0, "trips_measured": 0}
    policy_violations = 0

    for entry in entries:
        try:
            full = await history.get_entry(entry["id"])
        except Exception:  # noqa: BLE001 — a bad snapshot must not break the console
            continue
        snapshot = (full or {}).get("result_snapshot") or {}
        destination = entry.get("destination") or entry.get("goal") or "Trip"

        risk = (snapshot.get("risk_advisory") or {}).get("data") or {}
        level = str(risk.get("safety_level") or "").lower()
        emergency = (snapshot.get("emergency") or {}).get("data") or {}
        if level or snapshot.get("risk_advisory"):
            if level in risk_counts:
                risk_counts[level] += 1
            travellers.append(
                {
                    "trip_id": entry["id"],
                    "destination": destination,
                    "safety_level": level or "unknown",
                    "advisory": (risk.get("advisory_text") or "")[:220],
                    "embassy_phone": emergency.get("embassy_phone"),
                    "created_at": entry.get("created_at"),
                }
            )

        sus = (snapshot.get("sustainability") or {}).get("data") or {}
        try:
            co2 = float(sus.get("flight_co2_kg") or 0)
            offset = float(sus.get("carbon_offset_usd") or 0)
        except (TypeError, ValueError):
            co2 = offset = 0.0
        if co2 or offset:
            esg["total_co2_kg"] += co2
            esg["total_offset_usd"] += offset
            esg["trips_measured"] += 1

        flight_policy = ((snapshot.get("flight") or {}).get("data") or {}).get("policy") or {}
        policy_violations += len(flight_policy.get("violations") or [])

    return {
        "policy": {"configured": not policy_tools.is_empty(policy_doc), **policy_doc},
        "policy_violations": policy_violations,
        "duty_of_care": {
            "travellers": travellers,
            "risk_counts": risk_counts,
            "at_risk": risk_counts["caution"] + risk_counts["dangerous"],
        },
        "esg": {
            "total_co2_kg": round(esg["total_co2_kg"], 1),
            "total_offset_usd": round(esg["total_offset_usd"], 2),
            "trips_measured": esg["trips_measured"],
        },
    }
