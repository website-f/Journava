"""Auth endpoints — register · login · refresh · logout · me.

Security posture (spec: "highly standard"):
- Argon2id password hashing; only the hash is stored.
- Short-lived access JWT returned in the body; long-lived refresh token set as an
  httpOnly, SameSite cookie scoped to `/auth`, and rotated on every refresh.
- Login is rate-limited per email+IP (Redis) with lockout, and failures return a
  single generic message so the endpoint can't be used to enumerate accounts.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.auth import store
from app.auth.deps import current_claims
from app.core import auth as auth_core
from app.core import cache
from app.core.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{settings.api_prefix}/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COOKIE_PATH = f"{settings.api_prefix}/auth"


class RegisterRequest(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(min_length=1, max_length=200)


def _valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


def _set_refresh_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=raw,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        path=_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(settings.auth_cookie_name, path=_COOKIE_PATH)


async def _issue_session(
    user: dict[str, Any], response: Response, request: Request
) -> dict[str, Any]:
    access = auth_core.create_access_token(
        str(user["id"]),
        is_platform_admin=bool(user.get("is_platform_admin")),
        display_name=user.get("display_name"),
        email=user.get("email"),
    )
    raw, refresh_hash = auth_core.new_refresh_token()
    await store.create_session(
        user["id"], refresh_hash, request.headers.get("user-agent")
    )
    _set_refresh_cookie(response, raw)
    memberships = await store.memberships_for_user(str(user["id"]))
    return {
        "access_token": access,
        "token_type": "bearer",
        "expires_in": settings.access_token_ttl_minutes * 60,
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "display_name": user.get("display_name"),
            "is_platform_admin": bool(user.get("is_platform_admin")),
            "memberships": memberships,
        },
    }


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _throttle_check(key: str) -> None:
    client = await cache.get_redis()
    if client is None:
        return
    bucket = f"login:fail:{key}"
    count = await client.get(bucket)
    if count is not None and int(count) >= settings.login_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait a few minutes and try again.",
        )


async def _throttle_fail(key: str) -> None:
    client = await cache.get_redis()
    if client is None:
        return
    bucket = f"login:fail:{key}"
    count = await client.incr(bucket)
    if count == 1:
        await client.expire(bucket, settings.login_window_seconds)


async def _throttle_reset(key: str) -> None:
    client = await cache.get_redis()
    if client is not None:
        await client.delete(f"login:fail:{key}")


@router.post("/register")
async def register(body: RegisterRequest, request: Request, response: Response) -> dict[str, Any]:
    if not _valid_email(body.email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if await store.get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="An account with that email already exists.")

    user = await store.create_user(
        body.email.strip().lower(),
        auth_core.hash_password(body.password),
        body.display_name or body.email.split("@")[0],
    )
    if user is None:
        raise HTTPException(status_code=503, detail="Sign-up is unavailable — the database is down.")

    # Every user owns a personal workspace org (their trips live under it).
    org = await store.create_org(f"{user.get('display_name') or 'My'} Trips", kind="personal")
    if org:
        await store.add_membership(user["id"], org["id"], "owner")

    return await _issue_session(user, response, request)


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    throttle_key = f"{body.email.strip().lower()}|{_client_ip(request)}"
    await _throttle_check(throttle_key)

    user = await store.get_user_by_email(body.email)
    # Verify even when the user is missing so response timing doesn't reveal
    # whether an account exists.
    ok = auth_core.verify_password(user.get("password_hash") if user else None, body.password)
    if not user or not ok or not user.get("is_active", True):
        await _throttle_fail(throttle_key)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    await _throttle_reset(throttle_key)
    return await _issue_session(user, response, request)


@router.post("/refresh")
async def refresh(request: Request, response: Response) -> dict[str, Any]:
    raw = request.cookies.get(settings.auth_cookie_name)
    if not raw:
        raise HTTPException(status_code=401, detail="No session.")
    session = await store.get_valid_session(auth_core.hash_refresh(raw))
    if not session:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")

    # Rotate: the presented refresh token is single-use.
    await store.revoke_session(auth_core.hash_refresh(raw))
    user = await store.get_user_by_id(session["user_id"])
    if not user or not user.get("is_active", True):
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Account unavailable.")
    return await _issue_session(user, response, request)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    raw = request.cookies.get(settings.auth_cookie_name)
    if raw:
        await store.revoke_session(auth_core.hash_refresh(raw))
    _clear_refresh_cookie(response)
    return {"status": "signed_out"}


@router.get("/me")
async def me(request: Request) -> dict[str, Any]:
    claims = current_claims(request)
    user = await store.get_user_by_id(str(claims["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="Account not found.")
    memberships = await store.memberships_for_user(str(user["id"]))
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "display_name": user.get("display_name"),
        "is_platform_admin": bool(user.get("is_platform_admin")),
        "memberships": memberships,
    }
