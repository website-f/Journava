"""Saved research results — keep any result (flights / places / full trip) to
revisit or re-run. Shown in Research → Saved results; re-initiating loads the
snapshot straight back into the results view."""

from __future__ import annotations

import json
import logging
import math
import uuid
from typing import Any


def _json_safe(obj: Any) -> Any:
    """Strip NaN/Infinity floats (Postgres JSONB rejects them) so any real
    plan snapshot stores cleanly."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core import db
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/saved", tags=["saved"])


class SaveRequest(BaseModel):
    scope: str = "full_trip"
    kind: str = "result"  # result | trip (a confirmed trip)
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
    kind = body.kind if body.kind in ("result", "trip") else "result"
    dest = body.destination or ((body.results.get("chief") or {}).get("data") or {}).get("destination")
    async with pool.acquire() as conn:
        sid = await conn.fetchval(
            """INSERT INTO saved_results (user_id, scope, kind, title, destination, snapshot)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            uuid.UUID(uid) if uid else None, body.scope, kind, _title(body), dest,
            json.dumps(_json_safe(body.results), default=str),
        )
    return {"id": str(sid), "title": _title(body), "kind": kind}


class CloneSharedRequest(BaseModel):
    token: str


@router.post("/from-shared")
async def save_from_shared(body: CloneSharedRequest, request: Request) -> dict[str, Any]:
    """Clone a shared plan (by its public token) into the signed-in user's own
    trips, so a recipient of a shared link gets their own editable copy."""
    from app.shared import get_shared

    uid = _user_id(request)
    if not uid:
        return {"error": "Sign in to save this trip to your account."}
    shared = await get_shared(body.token)
    snap = shared.get("results") if isinstance(shared, dict) else None
    if not snap:
        return {"error": "This shared plan link is invalid or has expired."}

    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    dest = ((snap.get("chief") or {}).get("data") or {}).get("destination")
    title = (shared.get("title") or f"{dest or 'Shared'} trip")[:120]
    async with pool.acquire() as conn:
        sid = await conn.fetchval(
            """INSERT INTO saved_results (user_id, scope, kind, title, destination, snapshot)
               VALUES ($1, 'full_trip', 'trip', $2, $3, $4) RETURNING id""",
            uuid.UUID(uid), title, dest, json.dumps(_json_safe(snap), default=str),
        )
    return {"id": str(sid), "title": title, "kind": "trip"}


def _trip_summary(snap: dict[str, Any]) -> dict[str, Any]:
    """A compact card summary from a trip snapshot — what's in the plan and
    what still needs a choice — without shipping the whole snapshot."""
    flight = snap.get("flight") or {}
    fopts = flight.get("options") or []

    def _src(o: dict[str, Any]) -> str:
        return str(o.get("source") or (o.get("raw") or {}).get("source") or "")

    research = (snap.get("research") or {}).get("options") or []
    places = [o for o in research if o.get("kind") == "activity"]
    eats = [o for o in research if o.get("kind") == "restaurant"]
    scheduled = len((snap.get("itinerary") or {}).get("items") or [])
    ranking = (flight.get("data") or {}).get("ranking") or {}
    return {
        "flights": {
            "count": len(fopts),
            "atlas": sum(1 for o in fopts if _src(o) == "atlas"),
            "research": sum(1 for o in fopts if _src(o) == "camofox"),
            "bookable": sum(1 for o in fopts if o.get("bookable")),
            "picked": bool(ranking.get("chosen")),  # not chosen at plan time
        },
        "places": {"suggested": len(places), "scheduled": scheduled},
        "eats": {"suggested": len(eats)},
    }


@router.get("")
async def list_saved(request: Request, kind: str = "result") -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"saved": []}
    uid = _user_id(request)
    kind = kind if kind in ("result", "trip") else "result"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, scope, kind, title, destination, created_at, snapshot FROM saved_results "
            "WHERE (user_id = $1 OR $1 IS NULL) AND kind = $2 ORDER BY created_at DESC LIMIT 100",
            uuid.UUID(uid) if uid else None, kind,
        )
    out = []
    for r in rows:
        item = {
            "id": str(r["id"]), "scope": r["scope"], "kind": r["kind"], "title": r["title"],
            "destination": r["destination"],
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        }
        if kind == "trip":
            try:
                snap = r["snapshot"]
                snap = json.loads(snap) if isinstance(snap, str) else snap
                item["summary"] = _trip_summary(snap or {})
            except Exception:  # noqa: BLE001
                item["summary"] = None
        out.append(item)
    return {"saved": out}


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
