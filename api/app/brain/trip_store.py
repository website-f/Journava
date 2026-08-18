"""Active trip persistence — stores the latest plan result so the My Trip page
(spec §3.3) can load it independently of the Command Center.

Uses Gnosion for durable storage (same as TravelerProfile) with an in-process
fallback when Gnosion isn't available. Phase 3 will migrate to a Postgres
`trips` table for multi-trip history.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.brain import gnosion_client

logger = logging.getLogger(__name__)

#: Module-level cache of the active trip (survives Gnosion unavailability).
_active_trip: dict[str, Any] | None = None


def save_trip(plan_results: dict[str, Any]) -> None:
    """Persist the latest plan result as the active trip."""
    global _active_trip
    _active_trip = plan_results
    try:
        gnosion_client.remember(
            "active_trip",
            key="current",
            value=json.dumps(plan_results, default=str),
        )
        logger.debug("Active trip saved to Gnosion")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist trip to Gnosion: %s", exc)


def load_trip() -> dict[str, Any] | None:
    """Return the active trip, or None if no plan has been run yet."""
    global _active_trip
    if _active_trip is not None:
        return _active_trip
    # Try loading from Gnosion (e.g. after API restart).
    stored = gnosion_client.recall("active_trip", "current")
    if stored is not None:
        try:
            value = stored if isinstance(stored, str) else stored.get("value", "") if isinstance(stored, dict) else str(stored)
            _active_trip = json.loads(value)
            return _active_trip
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Could not parse stored trip: %s", exc)
    return None


def clear_trip() -> None:
    """Discard the active trip (e.g. when the user starts fresh)."""
    global _active_trip
    _active_trip = None
