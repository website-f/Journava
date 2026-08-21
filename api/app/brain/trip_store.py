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
from app.core.text import scrub_surrogates

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
    # Scrub lone surrogates from crawled text so the trip is always JSON-safe
    # (one such char in a flight title used to 500 GET /trip).
    plan_results = scrub_surrogates(plan_results)
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
            _active_trip = scrub_surrogates(json.loads(raw))
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
            save_trip(parsed)  # scrubs surrogates + refreshes the cache
            return _active_trip
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load trip from Postgres: %s", exc)
    return None


def clear_trip() -> None:
    """Discard the in-process active trip (e.g. when the user starts fresh)."""
    global _active_trip
    _active_trip = None


async def delete_active() -> None:
    """Remove the active trip everywhere — cache, brain, and Postgres snapshots."""
    global _active_trip
    _active_trip = None
    try:
        gnosion_client.remember("active_trip", key="current", value=json.dumps(None))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not clear trip in Gnosion: %s", exc)
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE trips SET plan_snapshot = NULL WHERE plan_snapshot IS NOT NULL")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not clear trip snapshots in Postgres: %s", exc)


async def update_itinerary(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Replace the active trip's itinerary items (drag-drop reorder / edits)."""
    trip = await load_trip_durable()
    if trip is None:
        return None
    itinerary = dict(trip.get("itinerary") or {})
    itinerary["items"] = items
    trip["itinerary"] = itinerary
    await save_trip_durable(trip)
    return trip


async def refine_itinerary(instruction: str | None = None) -> dict[str, Any] | None:
    """Ask the LLM to add activities and realign the day-by-day schedule.

    Falls back to the current items unchanged if the model is unavailable, so the
    button never dead-ends.
    """
    from app.core import llm

    trip = await load_trip_durable()
    if trip is None:
        return None
    itinerary = dict(trip.get("itinerary") or {})
    items = itinerary.get("items") or []
    chief_data = (trip.get("chief") or {}).get("data") or {}
    destination = chief_data.get("destination") or "the destination"

    system = (
        "You are Journava's itinerary planner. Given a day-by-day itinerary, return an "
        "IMPROVED version as JSON {\"items\": [...]}. Add 1-2 sensible activities/meals per "
        "day for the destination, keep existing good picks, and REALIGN start/end times so the "
        "day flows with no overlaps (realistic travel gaps). Each item: "
        "{day_index:int, kind:'activity'|'meal'|'transport'|'hotel'|'flight', title, "
        "starts_at:'HH:MM', ends_at:'HH:MM', cost_amount:number|null, cost_currency, reasoning}."
    )
    user = (
        f"Destination: {destination}\n"
        f"Instruction: {instruction or 'Add nicer places and rebalance the schedule.'}\n"
        f"Current itinerary JSON:\n{json.dumps({'items': items}, default=str)[:6000]}"
    )
    try:
        raw = await llm.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            agent="itinerary",
        )
        new_items = json.loads(raw).get("items")
        if isinstance(new_items, list) and new_items:
            items = new_items
    except Exception as exc:  # noqa: BLE001 — refine is best-effort
        logger.info("Itinerary refine failed, keeping current items: %s", exc)

    itinerary["items"] = items
    trip["itinerary"] = itinerary
    await save_trip_durable(trip)
    return trip


def _naive_schedule(picks: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    """Deterministic fallback: spread picks across days with sensible meal/activity
    slots so every day is filled even when the LLM is unavailable."""
    activities = [p for p in picks if str(p.get("kind")) != "restaurant"]
    meals = [p for p in picks if str(p.get("kind")) == "restaurant"]
    slots = [("09:00", "11:00", "activity"), ("11:30", "13:00", "activity"),
             ("13:00", "14:00", "meal"), ("15:00", "17:30", "activity"), ("19:00", "20:30", "meal")]
    items: list[dict[str, Any]] = []
    ai = mi = 0
    for day in range(days):
        for start, end, kind in slots:
            if kind == "meal" and mi < len(meals):
                p = meals[mi]; mi += 1
            elif ai < len(activities):
                p = activities[ai]; ai += 1; kind = "activity"
            else:
                continue
            items.append({"day_index": day, "kind": "meal" if kind == "meal" else "activity",
                          "title": p.get("title") or "Explore", "starts_at": start, "ends_at": end,
                          "reasoning": "Scheduled from your picks."})
    return items


async def build_itinerary(picks: list[dict[str, Any]], days: int, *, arrival: str | None = None) -> dict[str, Any] | None:
    """Schedule the traveller's PICKED places into a complete N-day itinerary —
    every day filled with smart, non-overlapping timing and meals at meal times."""
    from app.core import llm

    trip = await load_trip_durable()
    if trip is None:
        return None
    chief_data = (trip.get("chief") or {}).get("data") or {}
    destination = chief_data.get("destination") or "the destination"

    system = (
        "You are Journava's meticulous itinerary planner. Schedule the traveller's SELECTED "
        "places into a COMPLETE day-by-day plan across the given number of days. Rules: fill "
        "every day (morning + afternoon + evening), put restaurants at meal times "
        "(~08:00 breakfast, ~13:00 lunch, ~19:00 dinner), space activities with realistic "
        "travel gaps and NO overlaps, day 1 starts no earlier than the arrival time, and if there "
        "are more picks than fit keep the best and spread them; if fewer, add sensible "
        "free-time / rest / local-stroll blocks so no day is empty. Return JSON "
        "{\"items\":[{day_index:int(0-based), kind:'activity'|'meal'|'transport'|'hotel', title, "
        "starts_at:'HH:MM', ends_at:'HH:MM', reasoning}]}."
    )
    user = (
        f"Destination: {destination}\nDays: {days}\nArrival (day-1 earliest start): {arrival or '10:00'}\n"
        f"Selected places to schedule:\n{json.dumps(picks, default=str)[:6000]}"
    )
    items: list[dict[str, Any]] | None = None
    try:
        raw = await llm.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"}, agent="itinerary",
        )
        parsed = json.loads(raw).get("items")
        if isinstance(parsed, list) and parsed:
            items = [i for i in parsed if isinstance(i, dict) and i.get("title")]
    except Exception as exc:  # noqa: BLE001
        logger.info("build_itinerary LLM failed, using naive schedule: %s", exc)
    if not items:
        items = _naive_schedule(picks, max(1, days))

    itinerary = dict(trip.get("itinerary") or {})
    itinerary["items"] = items
    trip["itinerary"] = itinerary
    await save_trip_durable(trip)
    return trip
