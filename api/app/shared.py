"""Shareable compiled plans — a client with no account opens the interactive
view by token. Public read (allowlisted in AuthMiddleware); creation is
internal (called by the agency deliver flow)."""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from typing import Any

from fastapi import APIRouter

from app.core import db
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/shared", tags=["shared"])

#: In-process fallback when Postgres is unavailable.
_MEM: dict[str, dict[str, Any]] = {}


async def create_shared(*, snapshot: dict[str, Any], title: str = "Your Trip", org_id: str | None = None) -> str:
    """Persist a plan snapshot under a fresh token and return the token."""
    token = secrets.token_urlsafe(9)
    pool = await db.get_pool()
    if pool is None:
        _MEM[token] = {"title": title, "snapshot": snapshot}
        return token
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO shared_plans (token, org_id, title, snapshot) VALUES ($1, $2, $3, $4)",
                token,
                uuid.UUID(org_id) if org_id else None,
                title,
                json.dumps(snapshot, default=str),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not persist shared plan: %s", exc)
        _MEM[token] = {"title": title, "snapshot": snapshot}
    return token


@router.get("/{token}")
async def get_shared(token: str) -> dict[str, Any]:
    """Public: fetch a shared plan by token (no auth)."""
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT title, snapshot FROM shared_plans WHERE token = $1", token)
            if row:
                snap = row["snapshot"]
                snap = json.loads(snap) if isinstance(snap, str) else snap
                return {"title": row["title"], "results": snap}
        except Exception as exc:  # noqa: BLE001
            logger.warning("shared fetch failed: %s", exc)
    mem = _MEM.get(token)
    if mem:
        return {"title": mem["title"], "results": mem["snapshot"]}
    return {"error": "This shared plan link is invalid or has expired."}
