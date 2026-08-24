"""Redis cache + pub/sub bus.

Caching is a hard requirement, not an optimization: the free API tiers in spec
§9 only survive with 6–24h TTLs. Every tool call should go through `cached()`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)

_redis: Any = None

#: When to next attempt a connection after a failure. Without this, `_redis`
#: staying `None` means every cache read re-dials a dead server — which turns a
#: missing cache from "slower" into "much slower", the opposite of the point.
_retry_after: float = 0.0
_RETRY_BACKOFF_SECONDS = 30.0
_CONNECT_TIMEOUT_SECONDS = 3.0


async def get_redis() -> Any:
    """Lazily create the shared Redis client. Returns None when unreachable."""
    global _redis, _retry_after
    if _redis is not None:
        return _redis
    if time.monotonic() < _retry_after:
        return None

    try:
        from redis.asyncio import from_url

        client = from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=_CONNECT_TIMEOUT_SECONDS,
        )
        await asyncio.wait_for(client.ping(), timeout=_CONNECT_TIMEOUT_SECONDS)
        _redis = client
        _retry_after = 0.0
        logger.info("Redis cache ready")
    except Exception as exc:  # noqa: BLE001 - cache is optional, never fatal
        _redis = None
        _retry_after = time.monotonic() + _RETRY_BACKOFF_SECONDS
        logger.warning(
            "Redis unavailable (%s) — running without cache, retrying in %ds",
            exc,
            int(_RETRY_BACKOFF_SECONDS),
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def reset_backoff() -> None:
    """Force the next `get_redis()` to retry immediately."""
    global _retry_after
    _retry_after = 0.0


#: Process-lifetime cache hit/miss counters — a golden signal (how much work we
#: avoided) for the health snapshot.
_counters: dict[str, int] = {"hits": 0, "misses": 0}


def cache_stats() -> dict[str, Any]:
    total = _counters["hits"] + _counters["misses"]
    return {
        "hits": _counters["hits"],
        "misses": _counters["misses"],
        "hit_rate": round(_counters["hits"] / total, 3) if total else None,
    }


async def cached(
    key: str,
    producer: Callable[[], Awaitable[Any]],
    *,
    ttl: int | None = None,
) -> Any:
    """Return the cached value for `key`, else run `producer` and store it.

    Cache misses and Redis outages both fall through to the producer, so a dead
    cache degrades performance but never correctness.
    """
    client = await get_redis()
    namespaced = f"journava:{key}"

    if client is not None:
        try:
            hit = await client.get(namespaced)
            if hit is not None:
                _counters["hits"] += 1
                return json.loads(hit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache read failed for %s: %s", namespaced, exc)

    _counters["misses"] += 1
    value = await producer()

    if client is not None and value is not None:
        try:
            await client.set(
                namespaced,
                json.dumps(value, default=str),
                ex=ttl or settings.cache_ttl_short,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache write failed for %s: %s", namespaced, exc)

    return value
