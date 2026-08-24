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
import contextvars
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

#: Set inside a running job's task to a coroutine that stores partial results on
#: that job. Long-running work (a plan) reads it via `current_progress()` to
#: stream tiers back without knowing its own job id.
_PROGRESS: contextvars.ContextVar[Callable[[dict[str, Any]], Awaitable[None]] | None] = (
    contextvars.ContextVar("journava_job_progress", default=None)
)


def current_progress() -> Callable[[dict[str, Any]], Awaitable[None]] | None:
    """The partial-results setter for the job running in this task (or None)."""
    return _PROGRESS.get()


_PUBLIC_FIELDS = (
    "id",
    "kind",
    "status",
    "meta",
    "result",
    "partial",
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
        "partial": None,
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _JOBS[job_id] = job

    async def _set_partial(partial: dict[str, Any]) -> None:
        # In-memory only — polling reads _JOBS directly; persisting every tier to
        # Redis would be needless write amplification.
        job["partial"] = partial
        job["updated_at"] = _now()

    async def runner() -> None:
        _PROGRESS.set(_set_partial)
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
        await _maybe_notify(job)

    task = asyncio.create_task(runner())
    _TASKS[job_id] = task
    task.add_done_callback(lambda _t: _TASKS.pop(job_id, None))
    return job


async def _maybe_notify(job: dict[str, Any]) -> None:
    """Ping Telegram when a trip plan finishes — the "fire it and walk away" bit.

    Only plan jobs notify (not every task), and only if the traveller connected a
    bot. Never raises: a notification failure must not touch the job's outcome.
    """
    if job.get("kind") != "plan":
        return
    try:
        from app.tools import telegram

        meta = job.get("meta") or {}
        goal = str(meta.get("goal") or "").strip()
        scope = str(meta.get("scope") or "trip").replace("_", " ")
        if job.get("status") == "done":
            text = (
                f"✅ <b>Journava</b>\nYour <b>{scope}</b> plan is ready"
                + (f":\n<i>{goal[:180]}</i>" if goal else ".")
                + "\n\nOpen the app to view it."
            )
        else:
            text = (
                f"⚠️ <b>Journava</b>\nYour {scope} plan couldn't finish: "
                f"{str(job.get('error') or 'unknown error')[:180]}"
            )
        await telegram.notify(text)
    except Exception as exc:  # noqa: BLE001 — notification is best-effort
        logger.debug("plan notify failed: %s", exc)


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
