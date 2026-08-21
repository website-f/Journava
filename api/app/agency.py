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

from app.brain import history
from app.core.settings import settings

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
