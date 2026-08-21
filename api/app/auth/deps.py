"""FastAPI dependencies for reading the authenticated user and enforcing roles.

The ASGI `AuthMiddleware` has already validated the access token and put its
claims on `request.state.auth` for protected paths, so these dependencies are
cheap reads — no second decode. They exist for handlers that need the user id or
must gate on the platform-admin flag.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, status

from app.auth import store


def current_claims(request: Request) -> dict[str, Any]:
    claims = getattr(request.state, "auth", None)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return claims


def current_user_id(request: Request) -> str:
    return str(current_claims(request)["sub"])


def require_platform_admin(request: Request) -> dict[str, Any]:
    claims = current_claims(request)
    if not claims.get("pa"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin only"
        )
    return claims


_AGENCY_ROLES = {"owner", "admin", "staff"}


async def resolve_org_id(request: Request) -> str:
    """Best-effort org id for org-scoped features (policy, corporate console).

    Prefers an agency membership, falls back to the caller's first org, then to
    "default". Unlike `require_agency` this never 403s — a platform admin gets
    their platform org so support/testing works.
    """
    claims = current_claims(request)
    user_id = str(claims["sub"])
    memberships = await store.memberships_for_user(user_id)
    agency = next((m for m in memberships if m["org_kind"] == "agency"), None)
    chosen = agency or (memberships[0] if memberships else None)
    return str(chosen["org_id"]) if chosen else "default"


async def require_agency(request: Request) -> dict[str, Any]:
    """Resolve the caller's agency (supplier) org, or 403.

    A supplier user has a membership in an org of kind 'agency'. Returns that org
    context ({user_id, org_id, org_name, role}) so supplier endpoints can scope
    every read and write to it. Platform admins are allowed through against the
    first agency org (for support), if one exists.
    """
    claims = current_claims(request)
    user_id = str(claims["sub"])
    memberships = await store.memberships_for_user(user_id)
    for m in memberships:
        if m["org_kind"] == "agency" and m["role"] in _AGENCY_ROLES:
            return {
                "user_id": user_id,
                "org_id": m["org_id"],
                "org_name": m["org_name"],
                "role": m["role"],
            }
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="This area is for supplier (agency) accounts.",
    )
