"""LLM provider store — CRUD on the `llm_providers` table + usage logging.

Phase 3: the Engine management page lets the user configure their LLM failover
chain from the UI instead of environment variables. This module provides the
data layer that `llm.py` reads at call time.

When Postgres is unavailable, all read operations return empty results so the
LLM gateway falls back to the env-based chain (no regression).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from app.core import db

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Read operations
# --------------------------------------------------------------------------- #


async def list_providers() -> list[dict[str, Any]]:
    """Return all providers with the API key masked to last 4 characters."""
    pool = await db.get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, litellm_model, api_key, priority, enabled, max_rpm, "
                "created_at, updated_at FROM llm_providers ORDER BY priority, created_at"
            )
            return [_mask_row(dict(r)) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("list_providers failed: %s", exc)
        return []


async def get_chain() -> list[dict[str, Any]]:
    """Return enabled providers sorted by priority (for the LLM gateway)."""
    pool = await db.get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name, litellm_model, api_key, priority, max_rpm "
                "FROM llm_providers WHERE enabled = TRUE ORDER BY priority, created_at"
            )
            return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_chain failed: %s", exc)
        return []


# --------------------------------------------------------------------------- #
# Write operations
# --------------------------------------------------------------------------- #


async def create_provider(
    name: str,
    litellm_model: str,
    api_key: str,
    *,
    priority: int = 0,
    enabled: bool = True,
    max_rpm: int | None = None,
) -> dict[str, Any] | None:
    """Insert a new provider. Returns the created row (masked)."""
    pool = await db.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO llm_providers (name, litellm_model, api_key, priority, enabled, max_rpm)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   RETURNING id, name, litellm_model, api_key, priority, enabled, max_rpm, created_at, updated_at""",
                name, litellm_model, api_key, priority, enabled, max_rpm,
            )
            return _mask_row(dict(row)) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.error("create_provider failed: %s", exc)
        return None


async def update_provider(
    provider_id: str,
    **fields: Any,
) -> dict[str, Any] | None:
    """Update specific fields on a provider. Returns the updated row (masked)."""
    pool = await db.get_pool()
    if pool is None:
        return None
    allowed = {"name", "litellm_model", "api_key", "priority", "enabled", "max_rpm"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return None
    try:
        async with pool.acquire() as conn:
            set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
            query = f"UPDATE llm_providers SET {set_clauses}, updated_at = now() WHERE id = $1 RETURNING *"  # noqa: S608
            row = await conn.fetchrow(query, uuid.UUID(provider_id), *updates.values())
            return _mask_row(dict(row)) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.error("update_provider failed: %s", exc)
        return None


async def delete_provider(provider_id: str) -> bool:
    """Delete a provider by ID. Returns True if deleted."""
    pool = await db.get_pool()
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM llm_providers WHERE id = $1", uuid.UUID(provider_id)
            )
            return result == "DELETE 1"
    except Exception as exc:  # noqa: BLE001
        logger.error("delete_provider failed: %s", exc)
        return False


# --------------------------------------------------------------------------- #
# Test + stats
# --------------------------------------------------------------------------- #


async def get_provider_full(provider_id: str) -> dict[str, Any] | None:
    """Return a provider with the FULL api_key (for test calls)."""
    pool = await db.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM llm_providers WHERE id = $1", uuid.UUID(provider_id)
            )
            return dict(row) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.error("get_provider_full failed: %s", exc)
        return None


async def record_usage(
    provider_id: str | None,
    model: str,
    agent: str | None,
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    success: bool = True,
    error_msg: str | None = None,
) -> None:
    """Log a single LLM call to the usage table. Never raises."""
    pool = await db.get_pool()
    if pool is None:
        return
    try:
        pid = uuid.UUID(provider_id) if provider_id else None
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO llm_usage
                   (provider_id, model, agent, tokens_in, tokens_out, latency_ms, success, error_msg)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                pid, model, agent, tokens_in, tokens_out, latency_ms, success, error_msg,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("record_usage failed (non-critical): %s", exc)


async def get_stats() -> list[dict[str, Any]]:
    """Aggregate usage stats per provider (last 7 days)."""
    pool = await db.get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT
                     p.name,
                     p.litellm_model,
                     COUNT(*) AS total_calls,
                     SUM(CASE WHEN u.success THEN 1 ELSE 0 END) AS successful,
                     COALESCE(SUM(u.tokens_in), 0) AS tokens_in,
                     COALESCE(SUM(u.tokens_out), 0) AS tokens_out,
                     COALESCE(AVG(u.latency_ms), 0) AS avg_latency_ms
                   FROM llm_usage u
                   LEFT JOIN llm_providers p ON p.id = u.provider_id
                   WHERE u.created_at > now() - INTERVAL '7 days'
                   GROUP BY p.name, p.litellm_model
                   ORDER BY total_calls DESC"""
            )
            return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_stats failed: %s", exc)
        return []


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _mask_row(row: dict[str, Any]) -> dict[str, Any]:
    """Mask the api_key to show only the last 4 characters."""
    if "api_key" in row and row["api_key"]:
        key = str(row["api_key"])
        row["api_key"] = "•" * (len(key) - 4) + key[-4:] if len(key) > 4 else "••••"
    # Convert UUID to string for JSON serialization
    if "id" in row and hasattr(row["id"], "hex"):
        row["id"] = str(row["id"])
    return row
