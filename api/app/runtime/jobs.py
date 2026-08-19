"""Background job manager.

The Command Center dispatches work and gets a job id back immediately; the agents
run on the event loop, progress streams over the existing SSE bus, and the result
is fetched by id. Job records are held in-process (one API worker) and mirrored to
Redis so a poll still resolves after a brief restart and status survives a reload.

Deliberately small: no external queue. The travel plan and single-agent tasks are
seconds-to-minutes of async work, not a distributed pipeline — asyncio tasks are
the right size, and Redis covers durability without a broker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.core import cache

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 3600
_JOBS: dict[str, dict[str, Any]] = {}
_TASKS: dict[str, asyncio.Task] = {}

_PUBLIC_FIELDS = (
    "id",
    "kind",
    "status",
    "meta",
    "result",
    "error",
    "created_at",
    "updated_at",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _persist(job: dict[str, Any]) -> None:
    client = await cache.get_redis()
    if client is None:
        return
    try:
        await client.set(f"job:{job['id']}", json.dumps(job, default=str), ex=JOB_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 — durability is best-effort
        logger.debug("job persist failed: %s", exc)


def launch(
    kind: str,
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    meta: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Start `coro_factory()` in the background; return the job record at once."""
    job_id = uuid.uuid4().hex
    job: dict[str, Any] = {
        "id": job_id,
        "kind": kind,
        "status": "queued",
        "meta": meta or {},
        "user_id": user_id,
        "result": None,
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _JOBS[job_id] = job

    async def runner() -> None:
        job["status"] = "running"
        job["updated_at"] = _now()
        await _persist(job)
        try:
            job["result"] = await coro_factory()
            job["status"] = "done"
        except Exception as exc:  # noqa: BLE001 — a failed job is a state, not a crash
            logger.exception("job %s (%s) failed", job_id, kind)
            job["error"] = str(exc)
            job["status"] = "error"
        job["updated_at"] = _now()
        await _persist(job)

    task = asyncio.create_task(runner())
    _TASKS[job_id] = task
    task.add_done_callback(lambda _t: _TASKS.pop(job_id, None))
    return job


async def get(job_id: str) -> dict[str, Any] | None:
    job = _JOBS.get(job_id)
    if job is not None:
        return job
    client = await cache.get_redis()
    if client is None:
        return None
    raw = await client.get(f"job:{job_id}")
    return json.loads(raw) if raw else None


def public(job: dict[str, Any]) -> dict[str, Any]:
    """The client-facing view of a job (drops internal fields like user_id)."""
    return {field: job.get(field) for field in _PUBLIC_FIELDS}
