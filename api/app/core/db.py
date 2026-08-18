"""Postgres access (asyncpg pool) + first-run schema bootstrap.

Postgres holds the structured record — trips, bookings, itineraries, agent
events. Semantic memory lives in Gnosion instead (spec §5: Qdrant dropped).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)

_pool: Any = None

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


async def get_pool() -> Any:
    """Lazily create the asyncpg pool. Returns None when Postgres is unreachable."""
    global _pool
    if _pool is not None:
        return _pool
    try:
        import asyncpg

        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=1,
            max_size=10,
            command_timeout=30,
        )
    except Exception as exc:  # noqa: BLE001 - Phase 0 boots without a database
        logger.warning("Postgres unavailable (%s) — running without persistence", exc)
        _pool = None
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_schema() -> bool:
    """Apply the idempotent schema. Returns True when the schema is in place."""
    pool = await get_pool()
    if pool is None or not SCHEMA_FILE.exists():
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Schema init failed: %s", exc)
        return False


async def healthy() -> bool:
    pool = await get_pool()
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False
