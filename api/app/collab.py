"""Trip collaboration — the author of a saved trip invites people to view or
edit it, and everything is gated by the role the author granted.

Sharing has two levels, both intentionally kept:
  - **Public link** (`/trip/share` → `/s/{token}`) — anyone, no account, read-only.
  - **Collaboration** (this module) — named people, signed in, with a role
    (viewer | editor). An editor's saves write back to the SAME saved trip, so
    the plan is one shared document rather than a copy per person.

Only the owner can invite, change roles, or revoke. An invite is keyed by email
so it still lands if the person signs up later; if they already have an account
it is linked (and accepted) immediately so they can collaborate at once.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import store as auth_store
from app.core import db
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=settings.api_prefix, tags=["collab"])

Role = Literal["viewer", "editor"]


def _uid(request: Request) -> str | None:
    return (getattr(request.state, "auth", {}) or {}).get("sub")


def _require_uid(request: Request) -> str:
    uid = _uid(request)
    if not uid:
        raise HTTPException(status_code=401, detail="Sign in to manage collaborators.")
    return uid


class InviteRequest(BaseModel):
    email: str
    role: Role = "viewer"


class RoleUpdate(BaseModel):
    role: Role


class SnapshotUpdate(BaseModel):
    results: dict[str, Any]


async def _owner_id(conn: Any, saved_id: str) -> str | None:
    row = await conn.fetchrow("SELECT user_id FROM saved_results WHERE id = $1", uuid.UUID(saved_id))
    return str(row["user_id"]) if row and row["user_id"] else None


async def _role_for(saved_id: str, uid: str | None) -> str | None:
    """The current user's access to a saved trip: owner | editor | viewer | None."""
    if not uid:
        return None
    pool = await db.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            owner = await _owner_id(conn, saved_id)
            if owner and owner == uid:
                return "owner"
            row = await conn.fetchrow(
                "SELECT role FROM trip_collaborators WHERE saved_id = $1 AND user_id = $2",
                uuid.UUID(saved_id),
                uuid.UUID(uid),
            )
            return row["role"] if row else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("collab _role_for failed: %s", exc)
        return None


async def _claim_pending(uid: str | None) -> None:
    """Link any invites addressed to this user's email but sent before they had
    an account, so an invite always lands once they sign in."""
    if not uid:
        return
    pool = await db.get_pool()
    if pool is None:
        return
    try:
        user = await auth_store.get_user_by_id(uid)
        email = (user or {}).get("email")
        if not email:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE trip_collaborators SET user_id = $1, status = 'accepted' "
                "WHERE user_id IS NULL AND lower(email) = lower($2)",
                uuid.UUID(uid),
                email,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("collab _claim_pending failed: %s", exc)


def _collab_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "role": row["role"],
        "status": row["status"],
        "user_id": str(row["user_id"]) if row.get("user_id") else None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


# --------------------------------------------------------------------------- #
# Owner: invite / list / change role / revoke
# --------------------------------------------------------------------------- #


@router.post("/trip/{saved_id}/collaborators")
async def invite_collaborator(saved_id: str, body: InviteRequest, request: Request) -> dict[str, Any]:
    """Owner invites a person (by email) as viewer or editor."""
    uid = _require_uid(request)
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")

    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    async with pool.acquire() as conn:
        owner = await _owner_id(conn, saved_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="Trip not found.")
        if owner != uid:
            raise HTTPException(status_code=403, detail="Only the trip owner can invite collaborators.")

        # Link to an existing account (and accept) so they can collaborate now;
        # otherwise the invite waits on the email until they sign up.
        invitee = await auth_store.get_user_by_email(email)
        invitee_id = uuid.UUID(str(invitee["id"])) if invitee else None
        status = "accepted" if invitee else "invited"

        row = await conn.fetchrow(
            """INSERT INTO trip_collaborators (saved_id, email, user_id, role, status, invited_by)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (saved_id, email) DO UPDATE
                   SET role = EXCLUDED.role,
                       user_id = COALESCE(trip_collaborators.user_id, EXCLUDED.user_id),
                       status = CASE WHEN trip_collaborators.status = 'accepted'
                                     THEN 'accepted' ELSE EXCLUDED.status END
               RETURNING id, email, user_id, role, status, created_at""",
            uuid.UUID(saved_id),
            email,
            invitee_id,
            body.role,
            status,
            uuid.UUID(uid),
        )
    return {"collaborator": _collab_public(dict(row)), "linked": bool(invitee)}


@router.get("/trip/{saved_id}/collaborators")
async def list_collaborators(saved_id: str, request: Request) -> dict[str, Any]:
    """Owner (or any collaborator) sees who's on the trip and each person's role."""
    uid = _require_uid(request)
    role = await _role_for(saved_id, uid)
    if role is None:
        raise HTTPException(status_code=403, detail="You don't have access to this trip.")
    pool = await db.get_pool()
    if pool is None:
        return {"collaborators": [], "my_role": role}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, email, user_id, role, status, created_at FROM trip_collaborators "
            "WHERE saved_id = $1 ORDER BY created_at",
            uuid.UUID(saved_id),
        )
    return {"collaborators": [_collab_public(dict(r)) for r in rows], "my_role": role}


@router.patch("/trip/{saved_id}/collaborators/{collab_id}")
async def update_collaborator(saved_id: str, collab_id: str, body: RoleUpdate, request: Request) -> dict[str, Any]:
    uid = _require_uid(request)
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        if await _owner_id(conn, saved_id) != uid:
            raise HTTPException(status_code=403, detail="Only the owner can change roles.")
        row = await conn.fetchrow(
            "UPDATE trip_collaborators SET role = $3 WHERE id = $1 AND saved_id = $2 "
            "RETURNING id, email, user_id, role, status, created_at",
            uuid.UUID(collab_id),
            uuid.UUID(saved_id),
            body.role,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Collaborator not found.")
    return {"collaborator": _collab_public(dict(row))}


@router.delete("/trip/{saved_id}/collaborators/{collab_id}")
async def remove_collaborator(saved_id: str, collab_id: str, request: Request) -> dict[str, bool]:
    uid = _require_uid(request)
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        if await _owner_id(conn, saved_id) != uid:
            raise HTTPException(status_code=403, detail="Only the owner can revoke access.")
        result = await conn.execute(
            "DELETE FROM trip_collaborators WHERE id = $1 AND saved_id = $2",
            uuid.UUID(collab_id),
            uuid.UUID(saved_id),
        )
    return {"removed": result.endswith("1")}


# --------------------------------------------------------------------------- #
# Collaborator: what's shared with me, my access, and (editor) save-back
# --------------------------------------------------------------------------- #


@router.get("/trips/shared-with-me")
async def shared_with_me(request: Request) -> dict[str, Any]:
    """Trips other people have shared with the signed-in user."""
    uid = _uid(request)
    if not uid:
        return {"trips": []}
    await _claim_pending(uid)
    pool = await db.get_pool()
    if pool is None:
        return {"trips": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT s.id, s.title, s.destination, s.scope, s.created_at,
                      c.role, u.display_name AS owner_name, u.email AS owner_email
               FROM trip_collaborators c
               JOIN saved_results s ON s.id = c.saved_id
               LEFT JOIN users u ON u.id = s.user_id
               WHERE c.user_id = $1
               ORDER BY s.created_at DESC
               LIMIT 100""",
            uuid.UUID(uid),
        )
    trips = [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "destination": r["destination"],
            "scope": r["scope"],
            "role": r["role"],
            "owner": r["owner_name"] or r["owner_email"] or "A traveller",
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    return {"trips": trips}


@router.get("/trip/{saved_id}/access")
async def my_access(saved_id: str, request: Request) -> dict[str, Any]:
    """The current user's role on a saved trip — so the UI knows what to allow."""
    uid = _uid(request)
    await _claim_pending(uid)
    role = await _role_for(saved_id, uid)
    return {"role": role, "can_edit": role in ("owner", "editor"), "can_view": role is not None}


@router.post("/trip/{saved_id}/snapshot")
async def update_snapshot(saved_id: str, body: SnapshotUpdate, request: Request) -> dict[str, Any]:
    """Editor/owner saves changes back to the shared trip — one document, so the
    edit is visible to everyone on it."""
    uid = _require_uid(request)
    role = await _role_for(saved_id, uid)
    if role not in ("owner", "editor"):
        detail = (
            "You have view-only access to this trip."
            if role == "viewer"
            else "You don't have edit access to this trip."
        )
        raise HTTPException(status_code=403, detail=detail)
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE saved_results SET snapshot = $2 WHERE id = $1 RETURNING id",
            uuid.UUID(saved_id),
            json.dumps(body.results, default=str),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Trip not found.")
    return {"ok": True, "saved_id": saved_id}
