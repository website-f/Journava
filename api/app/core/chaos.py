"""Controlled fault injection for resilience testing (chaos engineering).

In-memory dependency toggles, DEV-GATED so they can never fire in production
unless explicitly opted in (CHAOS_ENABLED=1). An experiment flips a dependency
"down" and verifies the plan holds its steady state — a real flights section
still comes back — proving the Atlas → Amadeus → Camofox → LLM fallback ladder,
without touching prod or real bookings.
"""

from __future__ import annotations

import os

from app.core.settings import settings

_state: dict[str, bool] = {"atlas_outage": False, "camofox_outage": False}


def enabled() -> bool:
    """Chaos is only allowed outside production (or when explicitly opted in) —
    never inject faults into prod traffic unprompted."""
    return settings.environment != "production" or os.getenv("CHAOS_ENABLED") == "1"


def set_flag(target: str, on: bool) -> bool:
    if not enabled() or target not in _state:
        return False
    _state[target] = on
    return True


def clear() -> None:
    for key in _state:
        _state[key] = False


def atlas_down() -> bool:
    return enabled() and _state["atlas_outage"]


def camofox_down() -> bool:
    return enabled() and _state["camofox_outage"]


def status() -> dict[str, object]:
    return {"enabled": enabled(), "environment": settings.environment, **_state}
