"""Auth primitives — password hashing (Argon2id) and JWT / refresh tokens.

Kept deliberately small and dependency-light so it is easy to audit:

- **Passwords** use Argon2id (argon2-cffi defaults), the current OWASP choice.
  Only the hash is ever stored; `verify` is constant-time and never raises.
- **Access tokens** are short-lived HS256 JWTs carrying a minimal claim set
  (subject, platform-admin flag, display name). No secret or role list is baked
  in beyond what the UI needs — authorization is re-checked server-side.
- **Refresh tokens** are opaque random strings. Only their SHA-256 is stored
  (see `auth_sessions`), so a database leak yields nothing usable, and rotation
  simply revokes the old hash and stores a new one.

The signing secret comes from `JWT_SECRET`. If unset, it is derived from the
vault key / database URL so single-operator dev works out of the box — set an
explicit secret in production.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

from app.core.settings import settings

_hasher = PasswordHasher()  # Argon2id with library defaults
_ALGO = "HS256"


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Constant-time verify. Returns False on any mismatch or malformed hash."""
    if not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (Argon2Error, Exception):  # noqa: BLE001 — never leak why it failed
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Signing secret
# --------------------------------------------------------------------------- #


def _secret() -> str:
    if settings.jwt_secret:
        return settings.jwt_secret
    seed = f"journava-jwt::{settings.vault_encryption_key or settings.database_url}"
    return hashlib.sha256(seed.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Access tokens (JWT)
# --------------------------------------------------------------------------- #


def create_access_token(
    user_id: str,
    *,
    is_platform_admin: bool = False,
    display_name: str | None = None,
    email: str | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": "access",
        "pa": bool(is_platform_admin),
        "name": display_name,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGO)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode + validate an access token. Raises jwt exceptions on failure."""
    claims = jwt.decode(token, _secret(), algorithms=[_ALGO])
    if claims.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return claims


# --------------------------------------------------------------------------- #
# Refresh tokens (opaque; only the hash is stored)
# --------------------------------------------------------------------------- #


def new_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash). Give the raw to the client, store the hash."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh(raw)


def hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def refresh_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days)
