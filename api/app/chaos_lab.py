"""Chaos lab — dev-gated endpoints to inject and clear dependency faults, so a
resilience experiment can prove the plan holds its steady state under failure.

Direction 02 (Flights & Aviation → proactive disruption handling): the value
isn't only re-planning a delayed flight, it's that the whole plan degrades
gracefully when a data source dies. These endpoints let us demonstrate that on
demand. Never active in production unless CHAOS_ENABLED=1.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core import chaos
from app.core.settings import settings

router = APIRouter(prefix=f"{settings.api_prefix}/chaos", tags=["chaos"])


class Inject(BaseModel):
    target: Literal["atlas", "camofox"]
    action: Literal["down", "clear"]


@router.get("/status")
async def status() -> dict[str, object]:
    return chaos.status()


@router.post("/inject")
async def inject(body: Inject) -> dict[str, object]:
    if not chaos.enabled():
        return {"error": "Chaos is disabled in this environment.", "status": chaos.status()}
    chaos.set_flag(f"{body.target}_outage", body.action == "down")
    return {"ok": True, "status": chaos.status()}


@router.post("/clear")
async def clear() -> dict[str, object]:
    chaos.clear()
    return {"ok": True, "status": chaos.status()}
