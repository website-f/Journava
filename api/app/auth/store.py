"""Auth data access — users, organizations, memberships, refresh sessions.

Every function degrades to a safe empty/None when Postgres is unavailable, the
same contract the rest of the app follows, so a down database returns clean 401s
rather than 500s.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core import auth as auth_core
from app.core import db
from app.core.settings import settings

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    base = "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")
    return base or "org"


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #


async def get_user_by_email(email: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, display_name, password_hash, is_active, "
            "is_platform_admin FROM users WHERE lower(email) = lower($1)",
            email,
        )
    return dict(row) if row else None


async def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, email, display_name, is_active, is_platform_admin "
                "FROM users WHERE id = $1",
                uuid.UUID(user_id),
            )
    except (ValueError, Exception):  # noqa: BLE001
        return None
    return dict(row) if row else None


async def create_user(
    email: str,
    password_hash: str,
    display_name: str | None,
    *,
    is_platform_admin: bool = False,
) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO users (email, display_name, password_hash, is_platform_admin)
               VALUES ($1, $2, $3, $4)
               RETURNING id, email, display_name, is_active, is_platform_admin""",
            email,
            display_name,
            password_hash,
            is_platform_admin,
        )
    return dict(row) if row else None


# --------------------------------------------------------------------------- #
# Organizations & memberships
# --------------------------------------------------------------------------- #


async def create_org(name: str, kind: str = "personal") -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    slug = f"{_slugify(name)}-{uuid.uuid4().hex[:6]}"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO organizations (name, slug, kind) VALUES ($1, $2, $3) "
            "RETURNING id, name, slug, kind",
            name,
            slug,
            kind,
        )
    return dict(row) if row else None


async def add_membership(user_id: Any, org_id: Any, role: str) -> None:
    pool = await db.get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO memberships (user_id, org_id, role) VALUES ($1, $2, $3) "
            "ON CONFLICT (user_id, org_id) DO UPDATE SET role = EXCLUDED.role",
            user_id,
            org_id,
            role,
        )


async def memberships_for_user(user_id: str) -> list[dict[str, Any]]:
    pool = await db.get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT m.role, o.id AS org_id, o.name AS org_name,
                          o.slug AS org_slug, o.kind AS org_kind
                   FROM memberships m JOIN organizations o ON o.id = m.org_id
                   WHERE m.user_id = $1 ORDER BY o.created_at""",
                uuid.UUID(user_id),
            )
        return [
            {
                "org_id": str(r["org_id"]),
                "org_name": r["org_name"],
                "org_slug": r["org_slug"],
                "org_kind": r["org_kind"],
                "role": r["role"],
            }
            for r in rows
        ]
    except (ValueError, Exception):  # noqa: BLE001
        return []


# --------------------------------------------------------------------------- #
# Refresh sessions
# --------------------------------------------------------------------------- #


async def create_session(user_id: Any, refresh_hash: str, user_agent: str | None) -> None:
    pool = await db.get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO auth_sessions (user_id, refresh_hash, expires_at, user_agent) "
            "VALUES ($1, $2, $3, $4)",
            user_id,
            refresh_hash,
            auth_core.refresh_expiry(),
            (user_agent or "")[:400],
        )


async def get_valid_session(refresh_hash: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id, expires_at, revoked_at FROM auth_sessions "
            "WHERE refresh_hash = $1",
            refresh_hash,
        )
    if not row:
        return None
    if row["revoked_at"] is not None or row["expires_at"] <= datetime.now(UTC):
        return None
    return {"id": str(row["id"]), "user_id": str(row["user_id"])}


async def revoke_session(refresh_hash: str) -> None:
    pool = await db.get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE auth_sessions SET revoked_at = now() WHERE refresh_hash = $1 "
            "AND revoked_at IS NULL",
            refresh_hash,
        )


# --------------------------------------------------------------------------- #
# Demo seed (idempotent)
# --------------------------------------------------------------------------- #

#: The users created on first boot when SEED_DEMO_USERS is on. Passwords all use
#: settings.seed_demo_password. Printed to the log so an operator can sign in.
DEMO_USERS = [
    {
        "email": "admin@journava.test",
        "display_name": "Platform Admin",
        "platform_admin": True,
        "org": ("Journava Platform", "platform", "owner"),
    },
    {
        "email": "traveler@journava.test",
        "display_name": "Aisha Traveler",
        "platform_admin": False,
        "org": ("Aisha's Trips", "personal", "owner"),
    },
    {
        "email": "hotel@journava.test",
        "display_name": "Kinabalu Bay Resort",
        "platform_admin": False,
        "org": ("Kinabalu Bay Resort", "agency", "admin"),
    },
]


async def seed_demo_users() -> None:
    """Create the demo accounts once. Safe to call on every boot."""
    if not settings.seed_demo_users:
        return
    pool = await db.get_pool()
    if pool is None:
        return
    created: list[str] = []
    for spec in DEMO_USERS:
        if await get_user_by_email(spec["email"]):
            continue
        user = await create_user(
            spec["email"],
            auth_core.hash_password(settings.seed_demo_password),
            spec["display_name"],
            is_platform_admin=spec["platform_admin"],
        )
        if not user:
            continue
        org_name, org_kind, role = spec["org"]
        org = await create_org(org_name, kind=org_kind)
        if org:
            await add_membership(user["id"], org["id"], role)
        created.append(spec["email"])

    if created:
        logger.warning(
            "Seeded %d demo user(s): %s — password: %s (disable SEED_DEMO_USERS "
            "in production)",
            len(created),
            ", ".join(created),
            settings.seed_demo_password,
        )
