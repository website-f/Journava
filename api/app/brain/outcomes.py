"""Outcome learning — the self-improvement flywheel (spec §7 ③).

Accepted and rejected recommendations are the only signal Journava gets about
whether its reasoning was any good. Every outcome is written twice:

- to **Gnosion**, so the next plan recalls it and ranks accordingly;
- to **Postgres** (`decision_outcomes`), so the history survives and can be
  aggregated for the Analytics agent.

Without this the "gets smarter every trip" claim is decoration: the brain graph
never grows an Outcomes node and no preference is ever learned.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from app.agents.memory import MemoryAgent
from app.core import db, sse

logger = logging.getLogger(__name__)

OutcomeDomain = Literal["flight", "hotel", "activity", "restaurant", "research", "itinerary"]


async def record(
    domain: str,
    recommendation: dict[str, Any],
    accepted: bool,
    *,
    agent: str = "memory",
    trip_id: str | None = None,
    user_note: str | None = None,
) -> dict[str, Any]:
    """Record one accepted/rejected decision. Never raises."""
    # 1. Brain (hot path — this is what changes future rankings).
    try:
        MemoryAgent.record_outcome(domain, recommendation, accepted)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not write outcome to the brain: %s", exc)

    # 2. Postgres (durable history).
    persisted = await _persist(
        domain=domain,
        recommendation=recommendation,
        accepted=accepted,
        agent=agent,
        trip_id=trip_id,
        user_note=user_note,
    )

    label = recommendation.get("title") or recommendation.get("id") or domain
    sse.publish(
        "memory",
        "active",
        f"Learned: {label} was {'accepted' if accepted else 'rejected'}",
        data={"domain": domain, "accepted": accepted},
    )
    return {"recorded": True, "domain": domain, "accepted": accepted, "persisted": persisted}


async def _persist(
    *,
    domain: str,
    recommendation: dict[str, Any],
    accepted: bool,
    agent: str,
    trip_id: str | None,
    user_note: str | None,
) -> bool:
    pool = await db.get_pool()
    if pool is None:
        return False
    try:
        import uuid as _uuid

        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO decision_outcomes
                       (trip_id, agent, domain, recommendation, accepted, user_note)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                _uuid.UUID(trip_id) if trip_id else None,
                agent,
                domain,
                json.dumps(recommendation, default=str),
                accepted,
                user_note,
            )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist outcome: %s", exc)
        return False


async def stats() -> list[dict[str, Any]]:
    """Accepted/rejected tallies per domain — feeds the Engine + Analytics views."""
    pool = await db.get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT domain,
                          COUNT(*) FILTER (WHERE accepted)     AS accepted,
                          COUNT(*) FILTER (WHERE NOT accepted) AS rejected,
                          COUNT(*)                             AS total
                   FROM decision_outcomes
                   GROUP BY domain
                   ORDER BY total DESC"""
            )
        return [dict(row) for row in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read outcome stats: %s", exc)
        return []
