"""Redis cache + pub/sub bus.

Caching is a hard requirement, not an optimization: the free API tiers in spec
§9 only survive with 6–24h TTLs. Every tool call should go through `cached()`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)

_redis: Any = None


async def get_redis() -> Any:
    """Lazily create the shared Redis client. Returns None when unreachable."""
    global _redis
    if _redis is not None:
        return _redis
    try:
        from redis.asyncio import from_url

        client = from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _redis = client
    except Exception as exc:  # noqa: BLE001 - cache is optional, never fatal
        logger.warning("Redis unavailable (%s) — running without cache", exc)
        _redis = None
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


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
                return json.loads(hit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache read failed for %s: %s", namespaced, exc)

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
