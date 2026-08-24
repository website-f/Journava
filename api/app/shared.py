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
from pydantic import BaseModel

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


# --- Collaborative voting on a shared plan's places (public, no account) ----- #

#: In-process fallback: token -> {item -> set(voters)}
_VOTES_MEM: dict[str, dict[str, set[str]]] = {}


class VoteIn(BaseModel):
    item: str
    voter: str


async def _tallies(token: str, voter: str | None) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT item, count(*) AS n FROM plan_votes WHERE token = $1 GROUP BY item", token
                )
                mine_rows = (
                    await conn.fetch("SELECT item FROM plan_votes WHERE token = $1 AND voter = $2", token, voter)
                    if voter
                    else []
                )
            return {
                "tallies": {r["item"]: int(r["n"]) for r in rows},
                "mine": [r["item"] for r in mine_rows],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("vote tally failed: %s", exc)
    store = _VOTES_MEM.get(token, {})
    return {
        "tallies": {item: len(voters) for item, voters in store.items() if voters},
        "mine": [item for item, voters in store.items() if voter and voter in voters],
    }


@router.get("/{token}/votes")
async def get_votes(token: str, voter: str | None = None) -> dict[str, Any]:
    """Public: current vote tallies for a shared plan (+ this voter's picks)."""
    return await _tallies(token, voter)


@router.post("/{token}/vote")
async def cast_vote(token: str, body: VoteIn) -> dict[str, Any]:
    """Public: toggle a vote for a place on a shared plan (no account needed)."""
    item, voter = body.item.strip(), body.voter.strip()
    if not item or not voter:
        return {"error": "Pick a name before voting."}
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                deleted = await conn.execute(
                    "DELETE FROM plan_votes WHERE token=$1 AND item=$2 AND voter=$3", token, item, voter
                )
                if not deleted.endswith("1"):
                    await conn.execute(
                        "INSERT INTO plan_votes (token, item, voter) VALUES ($1,$2,$3) "
                        "ON CONFLICT (token, item, voter) DO NOTHING",
                        token, item, voter,
                    )
            return await _tallies(token, voter)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vote failed: %s", exc)
    # in-memory fallback
    store = _VOTES_MEM.setdefault(token, {})
    voters = store.setdefault(item, set())
    voters.discard(voter) if voter in voters else voters.add(voter)
    return await _tallies(token, voter)
