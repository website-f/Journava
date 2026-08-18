"""In-process SSE event bus for the live agent stream (spec §3.4).

Agents call `publish()`; every connected PWA client receives the event. A small
ring buffer replays recent activity so a client that connects mid-run still sees
context. Phase 2 can swap the backing store for Redis pub/sub to go multi-worker
without changing this interface.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal

AgentStatus = Literal["idle", "active", "working", "monitoring", "waiting", "error"]

REPLAY_SIZE = 50
QUEUE_SIZE = 100

_subscribers: set[asyncio.Queue[str]] = set()
_recent: deque[str] = deque(maxlen=REPLAY_SIZE)


def _encode(
    agent: str,
    status: AgentStatus,
    message: str,
    data: dict[str, Any] | None,
    caused_by: str | None,
) -> str:
    return json.dumps(
        {
            "id": str(uuid.uuid4()),
            "ts": datetime.now(UTC).isoformat(),
            "agent": agent,
            "status": status,
            "message": message,
            "data": data or {},
            "causedBy": caused_by,
        }
    )


def publish(
    agent: str,
    status: AgentStatus,
    message: str,
    *,
    data: dict[str, Any] | None = None,
    caused_by: str | None = None,
) -> None:
    """Fan an agent event out to every subscriber. Never blocks, never raises.

    Slow clients drop events rather than stalling an agent.
    """
    payload = _encode(agent, status, message, data, caused_by)
    _recent.append(payload)

    for queue in list(_subscribers):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass


async def subscribe() -> AsyncIterator[str]:
    """Yield SSE `data:` payloads, starting with the replay buffer.

    Emits a comment heartbeat every 15s so proxies keep the connection open.
    """
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)
    _subscribers.add(queue)
    try:
        for payload in list(_recent):
            yield payload
        while True:
            try:
                yield await asyncio.wait_for(queue.get(), timeout=15)
            except TimeoutError:
                yield "__heartbeat__"
    finally:
        _subscribers.discard(queue)


def subscriber_count() -> int:
    return len(_subscribers)
