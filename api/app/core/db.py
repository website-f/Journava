"""Postgres access (asyncpg pool) + first-run schema bootstrap.

Postgres holds the structured record — trips, bookings, itineraries, credentials,
agent events. Semantic memory lives in Gnosion instead (spec §5: Qdrant dropped).

Everything here degrades rather than raising: the API boots and serves without a
database, and `/health` reports it. Two details make that degradation cheap:

- **A failed connection is remembered.** `_pool` staying `None` used to mean every
  subsequent call re-attempted the connection; with ~4s per failed attempt and a
  dozen calls in one plan, an unreachable database turned a 5-second request into
  a 50-second one. Failures now back off.
- **Connection attempts are time-boxed.** `create_pool` is given an explicit
  timeout so a black-holed host cannot stall a request indefinitely.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)

_pool: Any = None

#: When to next attempt a connection after a failure, and how long to wait.
_retry_after: float = 0.0
_RETRY_BACKOFF_SECONDS = 30.0
#: Cap on a single connection attempt. Short: this is on the request path.
_CONNECT_TIMEOUT_SECONDS = 5.0

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


async def get_pool() -> Any:
    """Lazily create the asyncpg pool. Returns None when Postgres is unreachable.

    A recent failure short-circuits, so a down database costs one attempt every
    30 seconds rather than one attempt per query.
    """
    global _pool, _retry_after
    if _pool is not None:
        return _pool
    if time.monotonic() < _retry_after:
        return None

    try:
        import asyncpg

        _pool = await asyncio.wait_for(
            asyncpg.create_pool(
                dsn=settings.database_url,
                min_size=1,
                max_size=10,
                command_timeout=30,
                timeout=_CONNECT_TIMEOUT_SECONDS,
            ),
            timeout=_CONNECT_TIMEOUT_SECONDS + 2,
        )
        _retry_after = 0.0
        logger.info("Postgres pool ready")
    except Exception as exc:  # noqa: BLE001 — the app runs without a database
        _pool = None
        _retry_after = time.monotonic() + _RETRY_BACKOFF_SECONDS
        logger.warning(
            "Postgres unavailable (%s) — running without persistence, retrying in %ds",
            exc,
            int(_RETRY_BACKOFF_SECONDS),
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def reset_backoff() -> None:
    """Force the next `get_pool()` to retry immediately.

    Used after an operator fixes configuration, so they don't wait out a backoff
    window to see the effect.
    """
    global _retry_after
    _retry_after = 0.0


async def init_schema() -> bool:
    """Apply the idempotent schema. Returns True when the schema is in place."""
    pool = await get_pool()
    if pool is None or not SCHEMA_FILE.exists():
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
        logger.info("Schema applied")
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
