"""LLM provider store — the rotation pool behind the AI gateway.

Follows the Sejuk Ops router pattern, because it is the shape that survives free
tiers:

1. **Load & order** — enabled providers by `(priority, created_at)`; the Engine
   page reorders by drag.
2. **Filter** — skip anything cooled-down, `invalid`, or over its quota ceiling.
3. **Call** — first candidate that passes; on failure, rotate.
4. **Classify** — `429` → `rate_limited` + short cooldown; `401/403` → `invalid`
   (stop trying it); success → `healthy` + record usage.
5. **Fall back** — pool exhausted → local Ollama, which needs no key.

Two things worth stating plainly:

- **Keys are Fernet-encrypted** via `core.vault`. Only a masked hint leaves the
  process. Legacy plaintext rows are re-encrypted the first time they are read.
- **Quota is metered locally.** No provider exposes "remaining quota" in a usable
  standard way, so usage is counted in Redis against operator-set ceilings
  (requests/min, requests/day, tokens/day). The numbers are ours, not theirs, and
  the UI says so.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.core import cache, db, vault

logger = logging.getLogger(__name__)

ProviderStatus = Literal[
    "untested", "healthy", "rate_limited", "limit_reached", "invalid", "disabled"
]

#: How long a 429 sidelines a provider before it is retried.
RATE_LIMIT_COOLDOWN = timedelta(seconds=90)

#: The keyless local fallback. Always last, always available if it is running.
OLLAMA_FALLBACK = {
    "id": None,
    "name": "Ollama (local)",
    "model": "ollama/llama3.2",
    "api_key": None,
    "provider_id": None,
    "is_fallback": True,
}

_SELECT_COLUMNS = (
    "id, name, litellm_model, api_key, key_encrypted, masked_key, priority, "
    "enabled, max_rpm, max_rpd, max_tpd, status, status_detail, last_tested_at, "
    "last_used_at, cooldown_until, created_at, updated_at"
)


# --------------------------------------------------------------------------- #
# Key handling
# --------------------------------------------------------------------------- #


def _decrypt_key(row: dict[str, Any]) -> str | None:
    """Return the usable plaintext key for a row.

    Rows written before encryption existed hold plaintext; they are readable and
    get upgraded by `_reencrypt_legacy` rather than being treated as corrupt.
    """
    stored = row.get("api_key")
    if not stored:
        return None
    if row.get("key_encrypted"):
        return vault.decrypt(stored)
    return stored


async def _reencrypt_legacy(provider_id: Any, plaintext: str) -> None:
    """Upgrade a legacy plaintext key in place. Best effort."""
    pool = await db.get_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE llm_providers SET api_key = $2, key_encrypted = TRUE, "
                "masked_key = $3, updated_at = now() WHERE id = $1",
                provider_id,
                vault.encrypt(plaintext),
                vault.mask(plaintext),
            )
        logger.info("Re-encrypted a legacy plaintext LLM key")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not re-encrypt legacy key: %s", exc)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a row for the API. Never contains the key."""
    masked = row.get("masked_key") or ""
    if not masked and row.get("api_key") and not row.get("key_encrypted"):
        masked = vault.mask(str(row["api_key"]))
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "litellm_model": row["litellm_model"],
        "masked_key": masked,
        "priority": row["priority"],
        "enabled": row["enabled"],
        "max_rpm": row.get("max_rpm"),
        "max_rpd": row.get("max_rpd"),
        "max_tpd": row.get("max_tpd"),
        "status": row.get("status", "untested"),
        "status_detail": row.get("status_detail"),
        "cooling_down": _is_cooling_down(row),
        "last_tested_at": _iso(row.get("last_tested_at")),
        "last_used_at": _iso(row.get("last_used_at")),
        "created_at": _iso(row.get("created_at")),
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _is_cooling_down(row: dict[str, Any]) -> bool:
    until = row.get("cooldown_until")
    return isinstance(until, datetime) and until > datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #


async def list_providers() -> list[dict[str, Any]]:
    """Every provider with its health and live quota usage, key masked."""
    pool = await db.get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_SELECT_COLUMNS} FROM llm_providers "  # noqa: S608 — fixed columns
                "ORDER BY priority, created_at"
            )
        providers = []
        for row in rows:
            entry = _public(dict(row))
            entry["usage"] = await quota_usage(entry["id"], dict(row))
            providers.append(entry)
        return providers
    except Exception as exc:  # noqa: BLE001
        logger.warning("list_providers failed: %s", exc)
        return []


async def get_chain() -> list[dict[str, Any]]:
    """Ordered, usable candidates for the gateway.

    Skips what cannot help: disabled, invalid, cooling down, or over quota. An
    empty result is the signal for the env chain / Ollama fallback.
    """
    pool = await db.get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_SELECT_COLUMNS} FROM llm_providers "  # noqa: S608
                "WHERE enabled = TRUE AND status <> 'invalid' "
                "ORDER BY priority, created_at"
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_chain failed: %s", exc)
        return []

    chain: list[dict[str, Any]] = []
    for record in rows:
        row = dict(record)
        if _is_cooling_down(row):
            continue
        if await _over_quota(str(row["id"]), row):
            continue

        key = _decrypt_key(row)
        if key is None:
            # Undecryptable means the encryption key changed — say so once rather
            # than failing every call with a confusing provider error.
            logger.error(
                "Provider %s has an unreadable key (VAULT_ENCRYPTION_KEY changed?)",
                row["name"],
            )
            continue
        if not row.get("key_encrypted"):
            await _reencrypt_legacy(row["id"], key)

        chain.append(
            {
                "id": str(row["id"]),
                "name": row["name"],
                "litellm_model": row["litellm_model"],
                "api_key": key,
            }
        )
    return chain


async def get_provider_full(provider_id: str) -> dict[str, Any] | None:
    """One provider including its decrypted key — for the test endpoint only."""
    pool = await db.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_SELECT_COLUMNS} FROM llm_providers WHERE id = $1",  # noqa: S608
                uuid.UUID(provider_id),
            )
        if row is None:
            return None
        data = dict(row)
        return {
            "id": str(data["id"]),
            "name": data["name"],
            "litellm_model": data["litellm_model"],
            "api_key": _decrypt_key(data) or "",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_provider_full failed: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# Write
# --------------------------------------------------------------------------- #


async def create_provider(
    name: str,
    litellm_model: str,
    api_key: str,
    *,
    priority: int = 0,
    enabled: bool = True,
    max_rpm: int | None = None,
    max_rpd: int | None = None,
    max_tpd: int | None = None,
    status: ProviderStatus = "untested",
    status_detail: str | None = None,
) -> dict[str, Any] | None:
    """Insert a provider, encrypting the key."""
    pool = await db.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""INSERT INTO llm_providers
                       (name, litellm_model, api_key, key_encrypted, masked_key,
                        priority, enabled, max_rpm, max_rpd, max_tpd,
                        status, status_detail, last_tested_at)
                   VALUES ($1, $2, $3, TRUE, $4, $5, $6, $7, $8, $9, $10, $11,
                           CASE WHEN $10 = 'untested' THEN NULL ELSE now() END)
                   RETURNING {_SELECT_COLUMNS}""",  # noqa: S608 — fixed columns
                name,
                litellm_model,
                vault.encrypt(api_key),
                vault.mask(api_key),
                priority,
                enabled,
                max_rpm,
                max_rpd,
                max_tpd,
                status,
                status_detail,
            )
        return _public(dict(row)) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.error("create_provider failed: %s", exc)
        return None


async def update_provider(provider_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update a provider. An omitted key leaves the stored one untouched."""
    pool = await db.get_pool()
    if pool is None:
        return None

    allowed = {
        "name",
        "litellm_model",
        "priority",
        "enabled",
        "max_rpm",
        "max_rpd",
        "max_tpd",
        "status",
        "status_detail",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}

    new_key = fields.get("api_key")
    if new_key:
        updates["api_key"] = vault.encrypt(new_key)
        updates["key_encrypted"] = True
        updates["masked_key"] = vault.mask(new_key)
        # A rotated key deserves a fresh verdict rather than inheriting the old.
        updates.setdefault("status", "untested")
        updates["status_detail"] = None
        updates["cooldown_until"] = None

    if not updates:
        return None

    try:
        async with pool.acquire() as conn:
            assignments = ", ".join(f"{key} = ${i + 2}" for i, key in enumerate(updates))
            row = await conn.fetchrow(
                f"UPDATE llm_providers SET {assignments}, updated_at = now() "  # noqa: S608
                f"WHERE id = $1 RETURNING {_SELECT_COLUMNS}",
                uuid.UUID(provider_id),
                *updates.values(),
            )
        return _public(dict(row)) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.error("update_provider failed: %s", exc)
        return None


async def delete_provider(provider_id: str) -> bool:
    pool = await db.get_pool()
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM llm_providers WHERE id = $1", uuid.UUID(provider_id)
            )
        return result.endswith("1")
    except Exception as exc:  # noqa: BLE001
        logger.error("delete_provider failed: %s", exc)
        return False


async def reorder_providers(ordered_ids: list[str]) -> bool:
    """Apply a drag-and-drop rotation order in one transaction."""
    pool = await db.get_pool()
    if pool is None:
        return False
    try:
        async with pool.acquire() as conn, conn.transaction():
            for index, provider_id in enumerate(ordered_ids):
                await conn.execute(
                    "UPDATE llm_providers SET priority = $2, updated_at = now() WHERE id = $1",
                    uuid.UUID(provider_id),
                    index,
                )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("reorder_providers failed: %s", exc)
        return False


async def mark_status(
    provider_id: str | None,
    status: ProviderStatus,
    detail: str | None = None,
    *,
    cooldown: timedelta | None = None,
) -> None:
    """Record an observed outcome. Never raises — it is on the hot path."""
    if not provider_id:
        return
    pool = await db.get_pool()
    if pool is None:
        return
    try:
        until = datetime.now(UTC) + cooldown if cooldown else None
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE llm_providers SET status = $2, status_detail = $3, "
                "cooldown_until = COALESCE($4, cooldown_until), "
                "last_used_at = now(), updated_at = now() WHERE id = $1",
                uuid.UUID(provider_id),
                status,
                detail,
                until,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("mark_status failed: %s", exc)


async def reset_provider(provider_id: str) -> dict[str, Any] | None:
    """Clear a provider's status, cooldown and metered usage."""
    pool = await db.get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE llm_providers SET status = 'untested', status_detail = NULL, "
                "cooldown_until = NULL, updated_at = now() WHERE id = $1 "
                f"RETURNING {_SELECT_COLUMNS}",  # noqa: S608
                uuid.UUID(provider_id),
            )
        await _clear_quota(provider_id)
        return _public(dict(row)) if row else None
    except Exception as exc:  # noqa: BLE001
        logger.error("reset_provider failed: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# Quota metering (Redis)
# --------------------------------------------------------------------------- #


def _quota_keys(provider_id: str) -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "rpm": f"llmquota:{provider_id}:rpm:{now:%Y%m%d%H%M}",
        "rpd": f"llmquota:{provider_id}:rpd:{now:%Y%m%d}",
        "tpd": f"llmquota:{provider_id}:tpd:{now:%Y%m%d}",
    }


async def record_call(
    provider_id: str | None,
    *,
    tokens: int = 0,
) -> None:
    """Increment the local counters for one call. Never raises."""
    if not provider_id:
        return
    client = await cache.get_redis()
    if client is None:
        return
    keys = _quota_keys(provider_id)
    try:
        pipe = client.pipeline()
        pipe.incr(keys["rpm"])
        pipe.expire(keys["rpm"], 120)
        pipe.incr(keys["rpd"])
        pipe.expire(keys["rpd"], 172_800)
        if tokens:
            pipe.incrby(keys["tpd"], tokens)
            pipe.expire(keys["tpd"], 172_800)
        await pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.debug("record_call metering failed: %s", exc)


async def quota_usage(
    provider_id: str,
    row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Current metered usage against the configured ceilings."""
    client = await cache.get_redis()
    keys = _quota_keys(provider_id)
    counts = {"rpm": 0, "rpd": 0, "tpd": 0}
    if client is not None:
        try:
            values = await client.mget(keys["rpm"], keys["rpd"], keys["tpd"])
            counts = {
                name: int(value or 0)
                for name, value in zip(("rpm", "rpd", "tpd"), values, strict=True)
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("quota_usage read failed: %s", exc)

    limits = {
        "rpm": (row or {}).get("max_rpm"),
        "rpd": (row or {}).get("max_rpd"),
        "tpd": (row or {}).get("max_tpd"),
    }
    return {
        "counts": counts,
        "limits": limits,
        "metered_locally": True,
        "note": (
            "Counted by Journava against your ceilings — providers do not publish "
            "a standard remaining-quota figure."
        ),
    }


async def _over_quota(provider_id: str, row: dict[str, Any]) -> bool:
    """True when a configured ceiling has been reached."""
    limits = {
        "rpm": row.get("max_rpm"),
        "rpd": row.get("max_rpd"),
        "tpd": row.get("max_tpd"),
    }
    if not any(limits.values()):
        return False
    usage = await quota_usage(provider_id, row)
    counts = usage["counts"]
    for window, limit in limits.items():
        if limit and counts.get(window, 0) >= int(limit):
            await mark_status(
                provider_id,
                "limit_reached",
                f"Local {window} ceiling of {limit} reached",
            )
            return True
    return False


async def _clear_quota(provider_id: str) -> None:
    client = await cache.get_redis()
    if client is None:
        return
    try:
        await client.delete(*_quota_keys(provider_id).values())
    except Exception as exc:  # noqa: BLE001
        logger.debug("_clear_quota failed: %s", exc)


# --------------------------------------------------------------------------- #
# Usage log (Engine stats)
# --------------------------------------------------------------------------- #


async def record_usage(
    *,
    provider_id: str | None,
    model: str,
    agent: str | None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    success: bool = True,
    error_msg: str | None = None,
) -> None:
    """Append one call to `llm_usage`, and meter it. Never raises."""
    await record_call(provider_id, tokens=tokens_in + tokens_out)

    pool = await db.get_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO llm_usage
                       (provider_id, model, agent, tokens_in, tokens_out,
                        latency_ms, success, error_msg)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                uuid.UUID(provider_id) if provider_id else None,
                model,
                agent,
                tokens_in,
                tokens_out,
                latency_ms,
                success,
                error_msg,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("record_usage failed: %s", exc)


async def get_agent_stats() -> list[dict[str, Any]]:
    """Golden signals per AGENT over the last 24h — calls, error rate, p-latency,
    tokens — so an operator can see which agent is slow or failing."""
    pool = await db.get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT COALESCE(agent, 'other')          AS agent,
                          COUNT(*)                           AS calls,
                          COUNT(*) FILTER (WHERE NOT success) AS errors,
                          COALESCE(SUM(tokens_in + tokens_out), 0) AS tokens,
                          ROUND(AVG(latency_ms))             AS avg_ms,
                          ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)) AS p95_ms
                   FROM llm_usage
                   WHERE created_at > now() - interval '24 hours'
                   GROUP BY COALESCE(agent, 'other')
                   ORDER BY calls DESC"""
            )
        return [dict(row) for row in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_agent_stats failed: %s", exc)
        return []


async def get_stats() -> list[dict[str, Any]]:
    """Per-model usage over the last 7 days, for the Engine dashboard."""
    pool = await db.get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT model,
                          COUNT(*)                              AS calls,
                          COUNT(*) FILTER (WHERE success)       AS ok,
                          COUNT(*) FILTER (WHERE NOT success)   AS failed,
                          COALESCE(SUM(tokens_in), 0)           AS tokens_in,
                          COALESCE(SUM(tokens_out), 0)          AS tokens_out,
                          ROUND(AVG(latency_ms))                AS avg_latency_ms
                   FROM llm_usage
                   WHERE created_at > now() - interval '7 days'
                   GROUP BY model
                   ORDER BY calls DESC"""
            )
        return [dict(row) for row in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_stats failed: %s", exc)
        return []
