"""Saved research results — keep any result (flights / places / full trip) to
revisit or re-run. Shown in Research → Saved results; re-initiating loads the
snapshot straight back into the results view."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core import db
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/saved", tags=["saved"])


class SaveRequest(BaseModel):
    scope: str = "full_trip"
    title: str | None = None
    destination: str | None = None
    results: dict[str, Any]


def _user_id(request: Request) -> str | None:
    return (getattr(request.state, "auth", {}) or {}).get("sub")


def _title(body: SaveRequest) -> str:
    if body.title:
        return body.title[:120]
    dest = body.destination or ((body.results.get("chief") or {}).get("data") or {}).get("destination")
    label = (body.results.get("_scope") or {}).get("label") if isinstance(body.results.get("_scope"), dict) else None
    return f"{dest or 'Trip'} · {label or body.scope.replace('_', ' ')}"[:120]


@router.post("")
async def save(body: SaveRequest, request: Request) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    uid = _user_id(request)
    dest = body.destination or ((body.results.get("chief") or {}).get("data") or {}).get("destination")
    async with pool.acquire() as conn:
        sid = await conn.fetchval(
            """INSERT INTO saved_results (user_id, scope, title, destination, snapshot)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            uuid.UUID(uid) if uid else None, body.scope, _title(body), dest,
            json.dumps(body.results, default=str),
        )
    return {"id": str(sid), "title": _title(body)}


@router.get("")
async def list_saved(request: Request) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"saved": []}
    uid = _user_id(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, scope, title, destination, created_at FROM saved_results "
            "WHERE user_id = $1 OR $1 IS NULL ORDER BY created_at DESC LIMIT 100",
            uuid.UUID(uid) if uid else None,
        )
    return {
        "saved": [
            {"id": str(r["id"]), "scope": r["scope"], "title": r["title"], "destination": r["destination"],
             "created_at": r["created_at"].isoformat() if r.get("created_at") else None}
            for r in rows
        ]
    }


@router.get("/{saved_id}")
async def get_saved(saved_id: str, request: Request) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT scope, title, snapshot FROM saved_results WHERE id = $1", uuid.UUID(saved_id))
    if not row:
        return {"error": "not found"}
    snap = row["snapshot"]
    return {"scope": row["scope"], "title": row["title"], "results": json.loads(snap) if isinstance(snap, str) else snap}


@router.delete("/{saved_id}")
async def delete_saved(saved_id: str, request: Request) -> dict[str, bool]:
    pool = await db.get_pool()
    if pool is not None:
        uid = _user_id(request)
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM saved_results WHERE id = $1 AND (user_id = $2 OR $2 IS NULL)",
                uuid.UUID(saved_id), uuid.UUID(uid) if uid else None,
            )
    return {"deleted": True}
