"""Auth & multi-tenant identity (Phase 1).

- `store`      — users / organizations / memberships / sessions + demo seed.
- `deps`       — FastAPI dependencies (get_current_user, require_platform_admin).
- `middleware` — SSE-safe ASGI authn gate.
- `router`     — /auth register · login · refresh · logout · me.
"""
