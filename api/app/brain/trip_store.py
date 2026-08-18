"""Active trip persistence (spec §3.3, §5).

Three tiers, so a trip survives progressively harsher failures:

1. **Postgres** (`trips.plan_snapshot`) — the durable record. §5 puts trips in
   Postgres, and this is what makes a trip outlive a container restart.
2. **Gnosion** — the brain also remembers the active trip, which is what puts an
   "Active Trip" node in the knowledge graph.
3. **Process memory** — a last-resort cache so the app still works with neither.

Also owns `reconstruct_request`: turning a stored plan back into the
`TripRequest` that produced it. The disruption endpoint needs that to replan for
the right destination.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.schemas import TripRequest
from app.brain import gnosion_client
from app.core import db

logger = logging.getLogger(__name__)

#: Module-level cache of the active trip (tier 3).
_active_trip: dict[str, Any] | None = None

_TRIP_TITLE_FALLBACK = "Untitled trip"


# --------------------------------------------------------------------------- #
# Reconstruction
# --------------------------------------------------------------------------- #


def reconstruct_request(
    plan_results: dict[str, Any],
    *,
    goal: str = "trip recovery",
) -> TripRequest:
    """Rebuild the `TripRequest` behind a stored plan.

    Reads `chief.data["resolved_request"]` — the canonical mirror the Chief
    writes after folding its LLM parsing into the request. Falling back to the
    individual `data["destination"]`-style keys keeps older stored trips working.
    """
    chief_data = (plan_results.get("chief") or {}).get("data") or {}
    resolved = chief_data.get("resolved_request") or {}

    if not resolved:
        # Older snapshots (and the demo trip) mirror the fields at the top level.
        resolved = {
            key: chief_data.get(key)
            for key in (
                "destination",
                "origin",
                "start_date",
                "end_date",
                "travellers",
                "budget_amount",
                "budget_currency",
            )
            if chief_data.get(key) is not None
        }

    payload = {k: v for k, v in resolved.items() if v is not None}
    payload["goal"] = goal
    try:
        return TripRequest.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 — never block recovery on a bad record
        logger.warning("Could not reconstruct request (%s); using goal only", exc)
        return TripRequest(goal=goal)


def _trip_title(plan_results: dict[str, Any]) -> str:
    chief_data = (plan_results.get("chief") or {}).get("data") or {}
    destination = chief_data.get("destination")
    return f"Trip to {destination}" if destination else _TRIP_TITLE_FALLBACK


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def save_trip(plan_results: dict[str, Any]) -> None:
    """Persist the latest plan result as the active trip (tiers 2 + 3, sync)."""
    global _active_trip
    _active_trip = plan_results
    try:
        gnosion_client.remember(
            "active_trip",
            key="current",
            value=json.dumps(plan_results, default=str),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist trip to Gnosion: %s", exc)


async def save_trip_durable(plan_results: dict[str, Any]) -> str | None:
    """Persist to Postgres as well, returning the trip id when it landed.

    Separate from `save_trip` because agents call the sync path; only the API
    layer is in an async context and can reach the pool.
    """
    save_trip(plan_results)

    pool = await db.get_pool()
    if pool is None:
        return None

    request = reconstruct_request(plan_results, goal="stored plan")
    try:
        async with pool.acquire() as conn:
            trip_id = await conn.fetchval(
                """INSERT INTO trips
                       (title, goal, destination, origin, start_date, end_date,
                        travellers, budget_amount, budget_currency, status,
                        plan_snapshot)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'planning', $10)
                   RETURNING id""",
                _trip_title(plan_results),
                request.goal,
                request.destination,
                request.origin,
                request.start_date,
                request.end_date,
                request.travellers,
                request.budget_amount,
                request.budget_currency,
                json.dumps(plan_results, default=str),
            )
            return str(trip_id) if trip_id else None
    except Exception as exc:  # noqa: BLE001 — a failed write must not fail the plan
        logger.warning("Could not persist trip to Postgres: %s", exc)
        return None


def load_trip() -> dict[str, Any] | None:
    """Return the active trip from memory or Gnosion, or None."""
    global _active_trip
    if _active_trip is not None:
        return _active_trip

    stored = gnosion_client.recall("active_trip", "current")
    if stored is not None:
        try:
            if isinstance(stored, dict) and "value" in stored:
                raw = stored["value"]
            elif isinstance(stored, str):
                raw = stored
            else:
                raw = str(stored)
            _active_trip = json.loads(raw)
            return _active_trip
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Could not parse stored trip: %s", exc)
    return None


async def load_trip_durable() -> dict[str, Any] | None:
    """Return the active trip, consulting Postgres when the caches are cold.

    This is what makes a trip survive an API restart.
    """
    cached_trip = load_trip()
    if cached_trip is not None:
        return cached_trip

    pool = await db.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT plan_snapshot FROM trips "
                "WHERE plan_snapshot IS NOT NULL "
                "ORDER BY created_at DESC LIMIT 1"
            )
        if row and row["plan_snapshot"]:
            snapshot = row["plan_snapshot"]
            parsed = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
            save_trip(parsed)
            return parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load trip from Postgres: %s", exc)
    return None


def clear_trip() -> None:
    """Discard the in-process active trip (e.g. when the user starts fresh)."""
    global _active_trip
    _active_trip = None
