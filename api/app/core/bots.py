"""Notification bots — multiple Telegram bots, each independently toggleable.

A background trip plan pings every *enabled* bot. Tokens are Fernet-encrypted at
rest (reusing the vault cipher); the API only ever returns a masked hint. Falls
back to an in-process store when Postgres is unavailable, so the feature still
works in a bare demo.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core import db, vault

logger = logging.getLogger(__name__)

_COLS = "id, label, platform, token_encrypted, token_hint, chat_id, enabled, created_at, updated_at"
_memory: dict[str, dict[str, Any]] = {}


def _public(row: dict[str, Any]) -> dict[str, Any]:
    created = row.get("created_at")
    return {
        "id": str(row["id"]),
        "label": row.get("label"),
        "platform": row.get("platform", "telegram"),
        "token_hint": row.get("token_hint") or "",
        "chat_id": row.get("chat_id"),
        "enabled": bool(row.get("enabled", True)),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
    }


async def list_bots() -> list[dict[str, Any]]:
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT {_COLS} FROM notification_bots ORDER BY created_at"  # noqa: S608
                )
            return [_public(dict(row)) for row in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("bots.list_bots db miss: %s", exc)
    return [_public(rec) for rec in sorted(_memory.values(), key=lambda r: r.get("created_at") or 0)]


async def create_bot(
    label: str, token: str, chat_id: str, *, platform: str = "telegram", enabled: bool = True
) -> dict[str, Any] | None:
    bot_id = uuid.uuid4()
    encrypted = vault.encrypt(token)
    hint = vault.mask(token)
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"""INSERT INTO notification_bots
                            (id, label, platform, token_encrypted, token_hint, chat_id, enabled)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        RETURNING {_COLS}""",  # noqa: S608 — fixed columns
                    bot_id, label, platform, encrypted, hint, chat_id, enabled,
                )
            return _public(dict(row))
        except Exception as exc:  # noqa: BLE001
            logger.warning("bots.create_bot db failed, using memory: %s", exc)
    rec = {
        "id": bot_id, "label": label, "platform": platform,
        "token_encrypted": encrypted, "token_hint": hint, "chat_id": chat_id,
        "enabled": enabled, "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC),
    }
    _memory[str(bot_id)] = rec
    return _public(rec)


async def _get_raw(bot_id: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT {_COLS} FROM notification_bots WHERE id = $1", uuid.UUID(bot_id)  # noqa: S608
                )
            return dict(row) if row else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("bots._get_raw db miss: %s", exc)
    return _memory.get(bot_id)


async def update_bot(
    bot_id: str,
    *,
    label: str | None = None,
    token: str | None = None,
    chat_id: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any] | None:
    current = await _get_raw(bot_id)
    if current is None:
        return None
    new_label = label if label is not None else current.get("label")
    new_chat = chat_id if chat_id is not None else current.get("chat_id")
    new_enabled = enabled if enabled is not None else current.get("enabled", True)
    if token:
        encrypted = vault.encrypt(token)
        hint = vault.mask(token)
    else:
        encrypted = current.get("token_encrypted")
        hint = current.get("token_hint") or ""

    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"""UPDATE notification_bots
                        SET label=$2, token_encrypted=$3, token_hint=$4, chat_id=$5,
                            enabled=$6, updated_at=now()
                        WHERE id=$1 RETURNING {_COLS}""",  # noqa: S608
                    uuid.UUID(bot_id), new_label, encrypted, hint, new_chat, new_enabled,
                )
            return _public(dict(row)) if row else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("bots.update_bot db miss: %s", exc)
    rec = _memory.get(bot_id)
    if rec is None:
        return None
    rec.update(label=new_label, token_encrypted=encrypted, token_hint=hint, chat_id=new_chat, enabled=new_enabled)
    return _public(rec)


async def delete_bot(bot_id: str) -> bool:
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM notification_bots WHERE id = $1", uuid.UUID(bot_id)
                )
            if result.endswith("1"):
                return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("bots.delete_bot db miss: %s", exc)
    return _memory.pop(bot_id, None) is not None


async def credentials(bot_id: str) -> tuple[str, str] | None:
    """Decrypted (token, chat_id) for one bot — used to send a test message."""
    raw = await _get_raw(bot_id)
    if raw is None:
        return None
    token = vault.decrypt(raw["token_encrypted"]) if raw.get("token_encrypted") else None
    if not token or not raw.get("chat_id"):
        return None
    return token, str(raw["chat_id"])


async def email_credentials(channel_id: str) -> tuple[str, str, str] | None:
    """Decrypted (sender_email, app_password, recipient) for one email channel."""
    raw = await _get_raw(channel_id)
    if raw is None:
        return None
    sender = str(raw.get("label") or "").strip()
    password = vault.decrypt(raw["token_encrypted"]) if raw.get("token_encrypted") else None
    if not sender or not password:
        return None
    recipient = str(raw.get("chat_id") or sender).strip()
    return sender, password, recipient


async def enabled_targets() -> list[tuple[str, str, str]]:
    """(token, chat_id, label) for every enabled bot — the notify fan-out."""
    targets: list[tuple[str, str, str]] = []
    pool = await db.get_pool()
    rows: list[dict[str, Any]]
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                fetched = await conn.fetch(
                    f"SELECT {_COLS} FROM notification_bots WHERE enabled = TRUE"  # noqa: S608
                )
            rows = [dict(r) for r in fetched]
        except Exception as exc:  # noqa: BLE001
            logger.debug("bots.enabled_targets db miss: %s", exc)
            rows = [r for r in _memory.values() if r.get("enabled")]
    else:
        rows = [r for r in _memory.values() if r.get("enabled")]

    for row in rows:
        if (row.get("platform") or "telegram") != "telegram":
            continue  # email/other channels are fanned out separately
        token = vault.decrypt(row["token_encrypted"]) if row.get("token_encrypted") else None
        if token and row.get("chat_id"):
            targets.append((token, str(row["chat_id"]), str(row.get("label") or "bot")))
    return targets


async def email_targets() -> list[tuple[str, str, str]]:
    """(sender_email, app_password, recipient_email) for every enabled email channel.

    Stored in the same table with platform='email': label = the Gmail address
    (also the SMTP username), token = the app password, chat_id = the recipient
    (defaults to the sender)."""
    out: list[tuple[str, str, str]] = []
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                fetched = await conn.fetch(
                    f"SELECT {_COLS} FROM notification_bots WHERE enabled = TRUE AND platform = 'email'"  # noqa: S608
                )
            rows = [dict(r) for r in fetched]
        except Exception as exc:  # noqa: BLE001
            logger.debug("bots.email_targets db miss: %s", exc)
            rows = [r for r in _memory.values() if r.get("enabled") and r.get("platform") == "email"]
    else:
        rows = [r for r in _memory.values() if r.get("enabled") and r.get("platform") == "email"]

    for row in rows:
        sender = str(row.get("label") or "").strip()
        password = vault.decrypt(row["token_encrypted"]) if row.get("token_encrypted") else None
        recipient = str(row.get("chat_id") or sender).strip()
        if sender and password and recipient:
            out.append((sender, password, recipient))
    return out
