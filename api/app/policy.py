"""Corporate travel policy API (Phase 2.3).

An org's single active policy: fare caps, cabin rules, preferred carriers/hotels,
approval thresholds. Set it directly (PUT) or extract it from an uploaded policy
document (POST /policy/extract, used by the assistant's policy-doc upload). The
Flight/Hotel agents read the active policy and flag violations; the Agency
console reports compliance.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.auth.deps import resolve_org_id
from app.brain import policy_store
from app.core.settings import settings
from app.tools import policy as policy_tools

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/policy", tags=["policy"])


class PolicyBody(BaseModel):
    max_fare_amount: float | None = None
    fare_currency: str = "MYR"
    max_cabin: str | None = None
    preferred_carriers: list[str] = []
    max_hotel_per_night: float | None = None
    hotel_currency: str = "MYR"
    preferred_hotels: list[str] = []
    approval_threshold: float | None = None
    notes: str = ""


class ExtractBody(BaseModel):
    text: str


@router.get("")
async def get_policy(request: Request) -> dict[str, Any]:
    org_id = await resolve_org_id(request)
    stored = await policy_store.load_policy(org_id)
    policy = policy_tools.merge(stored)
    return {"configured": not policy_tools.is_empty(policy), "policy": policy}


@router.put("")
async def put_policy(body: PolicyBody, request: Request) -> dict[str, Any]:
    org_id = await resolve_org_id(request)
    policy = await policy_store.save_policy(org_id, body.model_dump())
    return {"configured": not policy_tools.is_empty(policy), "policy": policy}


@router.post("/extract")
async def extract_policy(body: ExtractBody, request: Request) -> dict[str, Any]:
    """Extract a structured policy from raw document text and save it."""
    org_id = await resolve_org_id(request)
    extracted = await policy_tools.extract_from_text(body.text)
    policy = await policy_store.save_policy(org_id, extracted)
    return {"configured": not policy_tools.is_empty(policy), "policy": policy}


@router.delete("")
async def delete_policy(request: Request) -> dict[str, Any]:
    org_id = await resolve_org_id(request)
    await policy_store.clear_policy(org_id)
    return {"configured": False, "policy": policy_tools.merge(None)}
