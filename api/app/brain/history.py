"""Search history — every scoped run, so it can be reopened without replaying.

A run costs real time and real tokens, so throwing the result away when the tab
closes is wasteful. Each entry keeps the question, the scope, and a snapshot of
the result, which means History can restore a past answer instantly.

Falls back to an in-process ring buffer when Postgres is absent, so the History
page is never empty just because the database is down.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any

from app.core import db

logger = logging.getLogger(__name__)

#: In-process fallback, newest first.
_recent: deque[dict[str, Any]] = deque(maxlen=50)

_COLUMNS = (
    "id, trip_id, scope, goal, destination, origin, agent_count, duration_ms, "
    "option_count, result_snapshot, created_at"
)


def _public(row: dict[str, Any], *, include_snapshot: bool = False) -> dict[str, Any]:
    snapshot = row.get("result_snapshot")
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except (ValueError, TypeError):
            snapshot = None
    entry = {
        "id": str(row["id"]),
        "trip_id": str(row["trip_id"]) if row.get("trip_id") else None,
        "scope": row["scope"],
        "goal": row["goal"],
        "destination": row.get("destination"),
        "origin": row.get("origin"),
        "agent_count": row.get("agent_count", 0),
        "duration_ms": row.get("duration_ms"),
        "option_count": row.get("option_count", 0),
        "created_at": (
            row["created_at"].isoformat()
            if isinstance(row.get("created_at"), datetime)
            else row.get("created_at")
        ),
    }
    if include_snapshot:
        entry["result_snapshot"] = snapshot
    return entry


def _count_options(results: dict[str, Any]) -> int:
    total = 0
    for key, value in results.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        total += len(value.get("options") or [])
    return total


async def record(
    *,
    scope: str,
    goal: str,
    results: dict[str, Any],
    duration_ms: int | None = None,
    trip_id: str | None = None,
) -> dict[str, Any]:
    """Store one completed run. Never raises."""
    chief_data = (results.get("chief") or {}).get("data") or {}
    scope_meta = results.get("_scope") or {}
    entry = {
        "id": uuid.uuid4(),
        "trip_id": uuid.UUID(trip_id) if trip_id else None,
        "scope": scope,
        "goal": goal[:500],
        "destination": chief_data.get("destination"),
        "origin": chief_data.get("origin"),
        "agent_count": len(scope_meta.get("agents") or []),
        "duration_ms": duration_ms,
        "option_count": _count_options(results),
        "result_snapshot": results,
        "created_at": datetime.now(UTC),
    }

    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"""INSERT INTO search_history
                           (id, trip_id, scope, goal, destination, origin,
                            agent_count, duration_ms, option_count, result_snapshot)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                       RETURNING {_COLUMNS}""",  # noqa: S608 — fixed columns
                    entry["id"],
                    entry["trip_id"],
                    scope,
                    entry["goal"],
                    entry["destination"],
                    entry["origin"],
                    entry["agent_count"],
                    duration_ms,
                    entry["option_count"],
                    json.dumps(results, default=str),
                )
            return _public(dict(row))
        except Exception as exc:  # noqa: BLE001 — history must never fail a plan
            logger.warning("Could not persist search history: %s", exc)

    _recent.appendleft(entry)
    return _public(entry)


async def list_entries(limit: int = 50, scope: str | None = None) -> list[dict[str, Any]]:
    """Recent runs, newest first."""
    pool = await db.get_pool()
    if pool is not None:
        try:
            query = f"SELECT {_COLUMNS} FROM search_history"  # noqa: S608
            params: list[Any] = []
            if scope:
                query += " WHERE scope = $1"
                params.append(scope)
            query += f" ORDER BY created_at DESC LIMIT ${len(params) + 1}"
            params.append(limit)
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            if rows:
                return [_public(dict(row)) for row in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("history.list_entries failed: %s", exc)

    entries = [e for e in _recent if not scope or e["scope"] == scope]
    return [_public(entry) for entry in entries[:limit]]


async def get_entry(entry_id: str) -> dict[str, Any] | None:
    """One run including its full result snapshot, for reopening."""
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT {_COLUMNS} FROM search_history WHERE id = $1",  # noqa: S608
                    uuid.UUID(entry_id),
                )
            if row:
                return _public(dict(row), include_snapshot=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("history.get_entry failed: %s", exc)

    for entry in _recent:
        if str(entry["id"]) == entry_id:
            return _public(entry, include_snapshot=True)
    return None


async def delete_entry(entry_id: str) -> bool:
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM search_history WHERE id = $1", uuid.UUID(entry_id)
                )
            if result.endswith("1"):
                return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("history.delete_entry failed: %s", exc)

    for entry in list(_recent):
        if str(entry["id"]) == entry_id:
            _recent.remove(entry)
            return True
    return False
