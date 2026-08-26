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

#: Every org kind that is a business/B2B tenant (as opposed to a personal
#: traveller or the platform org). Gating on this SET rather than the single
#: literal "agency" means a hotel/supplier org — however its kind was labelled —
#: still reaches the console instead of silently dropping to the consumer app.
_B2B_KINDS = {"agency", "supplier", "hotel", "business", "corporate", "tmc", "operator"}


def _is_b2b(kind: str | None) -> bool:
    return bool(kind) and kind not in ("personal", "platform")


async def resolve_org_id(request: Request) -> str:
    """Best-effort org id for org-scoped features (policy, corporate console).

    Prefers a B2B membership, falls back to the caller's first org, then to
    "default". Unlike `require_agency` this never 403s — a platform admin gets
    their platform org so support/testing works.
    """
    claims = current_claims(request)
    user_id = str(claims["sub"])
    memberships = await store.memberships_for_user(user_id)
    b2b = next((m for m in memberships if _is_b2b(m.get("org_kind"))), None)
    chosen = b2b or (memberships[0] if memberships else None)
    return str(chosen["org_id"]) if chosen else "default"


async def require_agency(request: Request) -> dict[str, Any]:
    """Resolve the caller's business (agency / hotel / supplier) org, or 403.

    A B2B user has a membership in an org whose kind is not personal/platform.
    Returns that org context ({user_id, org_id, org_name, role}) so console
    endpoints can scope every read and write to it.
    """
    claims = current_claims(request)
    user_id = str(claims["sub"])
    memberships = await store.memberships_for_user(user_id)
    for m in memberships:
        if (m["org_kind"] in _B2B_KINDS or _is_b2b(m.get("org_kind"))) and m["role"] in _AGENCY_ROLES:
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
