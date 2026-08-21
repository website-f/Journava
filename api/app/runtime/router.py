"""Runtime endpoints — capability catalog + background jobs.

- `GET  /agents/catalog`  — the capability manifest (travel + task packs).
- `POST /jobs/plan`       — run a travel plan in the background; returns a job id.
- `POST /jobs/task`       — run a single task agent (e.g. email_replier) in the background.
- `GET  /jobs/{id}`       — poll status + result.

The heavy work runs off-request so the Command Center can show "your agents are
working…" and stream the live log, then fetch the result by id.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.agents.memory import MemoryAgent
from app.agents.schemas import TripRequest
from app.brain import history, trip_store
from app.core.settings import settings
from app.graph import scopes
from app.graph.supervisor import run_plan
from app.runtime import catalog as catalog_mod
from app.runtime import jobs, recommendations, tasks

router = APIRouter(prefix=settings.api_prefix, tags=["runtime"])


@router.get("/agents/catalog")
async def agents_catalog() -> dict[str, Any]:
    """Every agent the platform can run, by domain and capability."""
    return catalog_mod.catalog()


@router.get("/recommendations")
async def recommendations_feed(request: Request, limit: int = 12) -> dict[str, Any]:
    """Personalized home cards derived from the traveller's own history.

    The home shows the first few; a `limit` up to 24 backs the "See more" drawer.
    """
    claims = getattr(request.state, "auth", {}) or {}
    items = await recommendations.build(claims.get("sub"), limit=max(1, min(limit, 24)))
    return {"recommendations": items}


# --------------------------------------------------------------------------- #
# Task jobs (domain-agnostic single agents)
# --------------------------------------------------------------------------- #


class TaskJobRequest(BaseModel):
    agent: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/jobs/task")
async def create_task_job(body: TaskJobRequest, request: Request) -> dict[str, Any]:
    if body.agent not in tasks.TASK_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown task agent '{body.agent}'")
    claims = getattr(request.state, "auth", {}) or {}
    job = jobs.launch(
        "task",
        lambda: tasks.run_task(body.agent, body.payload),
        meta={"agent": body.agent},
        user_id=claims.get("sub"),
    )
    return jobs.public(job)


# --------------------------------------------------------------------------- #
# Plan jobs (the travel graph, backgrounded)
# --------------------------------------------------------------------------- #


class PlanJobRequest(TripRequest):
    scope: str = scopes.DEFAULT_SCOPE


async def _run_plan_job(body: PlanJobRequest, user_id: str | None) -> dict[str, Any]:
    """Mirror of the synchronous /plan handler, run inside a background job."""
    scope = scopes.get(body.scope)
    trip_request = TripRequest.model_validate(
        body.model_dump(exclude={"scope"}, exclude_none=True)
    )
    profile = MemoryAgent.load_profile(user_id)

    started = time.monotonic()
    results = await run_plan(trip_request, profile, scope=scope)
    duration_ms = int((time.monotonic() - started) * 1000)

    # Document what the agents just learned into the knowledge library. Must
    # never fail the plan — it's best-effort post-processing.
    from app.brain import knowledge

    try:
        await knowledge.record_from_plan(results)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("journava").warning("record_from_plan failed", exc_info=True)

    # NOTE: a plan is NOT auto-saved as the active trip. It becomes the trip only
    # when the traveller taps "Add to my trip" (POST /trip/save) after reviewing
    # and picking flights/hotels. Auto-saving here made unconfirmed plans appear
    # on the Trip page.

    entry = await history.record(
        scope=scope.slug,
        goal=trip_request.goal,
        results=results,
        duration_ms=duration_ms,
    )
    return {
        "results": results,
        "scope": scope.slug,
        "history_id": entry.get("id"),
        "duration_ms": duration_ms,
    }


@router.post("/jobs/plan")
async def create_plan_job(body: PlanJobRequest, request: Request) -> dict[str, Any]:
    claims = getattr(request.state, "auth", {}) or {}
    user_id = claims.get("sub")
    job = jobs.launch(
        "plan",
        lambda: _run_plan_job(body, user_id),
        meta={"scope": body.scope, "goal": body.goal},
        user_id=user_id,
    )
    return jobs.public(job)


# --------------------------------------------------------------------------- #
# Job status
# --------------------------------------------------------------------------- #


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job = await jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return jobs.public(job)
