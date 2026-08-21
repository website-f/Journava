"""Org-scoped corporate travel policy persistence (Phase 2.3).

One policy per org in Postgres (`org_policies`). A process-level cache of the
most-recently-active policy lets the Flight/Hotel agents read it synchronously
inside the graph without threading org context through every node — the demo is
effectively single-tenant, and the durable record stays org-scoped.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core import db
from app.tools import policy as policy_tools

logger = logging.getLogger("journava")

#: Last policy saved/loaded this process — what the agents apply.
_active: dict[str, Any] | None = None


def active() -> dict[str, Any] | None:
    """The policy the agents should apply right now (process cache), or None."""
    return _active


def set_active(policy: dict[str, Any] | None) -> None:
    global _active
    _active = policy


async def save_policy(org_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    """Upsert the org's policy and warm the active cache. Returns the merged policy."""
    merged = policy_tools.merge(policy)
    set_active(merged)
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO org_policies (org_id, policy, updated_at)
                       VALUES ($1, $2, now())
                       ON CONFLICT (org_id)
                       DO UPDATE SET policy = EXCLUDED.policy, updated_at = now()""",
                    org_id,
                    json.dumps(merged, default=str),
                )
        except Exception as exc:  # noqa: BLE001 — never fail on a bad write
            logger.warning("Could not persist org policy: %s", exc)
    return merged


async def load_policy(org_id: str) -> dict[str, Any] | None:
    """Fetch the org's stored policy (and warm the active cache), or None."""
    pool = await db.get_pool()
    if pool is None:
        return _active
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT policy FROM org_policies WHERE org_id = $1", org_id)
        if row and row["policy"]:
            raw = row["policy"]
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            merged = policy_tools.merge(parsed)
            set_active(merged)
            return merged
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load org policy: %s", exc)
    return None


async def clear_policy(org_id: str) -> None:
    """Remove the org's policy (and clear the active cache)."""
    set_active(None)
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM org_policies WHERE org_id = $1", org_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not clear org policy: %s", exc)
