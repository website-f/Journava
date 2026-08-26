"""SSE-safe ASGI authentication gate.

Deliberately a *pure ASGI* middleware, not `BaseHTTPMiddleware`: the latter
buffers the response, which breaks the `/events` SSE stream. This one only reads
the request, and either rejects with a 401 or passes the scope through untouched,
so streaming keeps working.

Public paths (health, docs, and everything under `/auth/`) skip the check.
Everything else needs a valid access token — from the `Authorization: Bearer`
header, or (for the header-less EventSource on `/events`) a `?token=` query param.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import jwt

from app.core import auth as auth_core
from app.core.settings import settings

_PUBLIC_EXACT = {
    "/",
    "/health",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/docs/oauth2-redirect",
    "/favicon.ico",
    # Only the token-less auth endpoints are public. `/auth/me` deliberately is
    # NOT here — it requires a valid access token like every other route.
    f"{settings.api_prefix}/auth/register",
    f"{settings.api_prefix}/auth/login",
    f"{settings.api_prefix}/auth/refresh",
    f"{settings.api_prefix}/auth/logout",
}


#: Areas only a platform admin may touch — the LLM rotation pool and the API
#: Vault of third-party credentials. Enforced here so authz lives in one place
#: rather than being re-declared on every endpoint.
_ADMIN_PREFIXES = (
    f"{settings.api_prefix}/engine",
    f"{settings.api_prefix}/vault",
)


#: Public path prefixes — a client with no account opens a shared plan by token.
_PUBLIC_PREFIXES = (
    f"{settings.api_prefix}/shared/",
    f"{settings.api_prefix}/packages/",  # the public Package Builder funnel
)


def _is_public(path: str) -> bool:
    return path in _PUBLIC_EXACT or any(path.startswith(p) for p in _PUBLIC_PREFIXES)


def _needs_admin(path: str) -> bool:
    return any(path.startswith(p) for p in _ADMIN_PREFIXES)


class AuthMiddleware:
    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")
        if method == "OPTIONS" or _is_public(path):
            await self.app(scope, receive, send)
            return

        token = self._token(scope, path)
        if not token:
            await self._reject(send, "Not authenticated")
            return
        try:
            claims = auth_core.decode_access_token(token)
        except jwt.ExpiredSignatureError:
            await self._reject(send, "Token expired")
            return
        except Exception:  # noqa: BLE001
            await self._reject(send, "Invalid token")
            return

        if _needs_admin(path) and not claims.get("pa"):
            await self._reject(send, "Platform admin only", status=403)
            return

        scope.setdefault("state", {})["auth"] = claims
        await self.app(scope, receive, send)

    @staticmethod
    def _token(scope, path) -> str | None:  # noqa: ANN001
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                raw = value.decode("latin-1")
                if raw.lower().startswith("bearer "):
                    return raw[7:].strip()
        # EventSource cannot set headers, so accept a short-lived token in the
        # query string for the SSE endpoint only.
        if path.endswith("/events"):
            params = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            found = params.get("token") or params.get("access_token")
            if found:
                return found[0]
        return None

    @staticmethod
    async def _reject(send, detail: str, status: int = 401) -> None:  # noqa: ANN001
        body = json.dumps({"detail": detail}).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        if status == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
