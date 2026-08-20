"""Telegram Bot notifications.

Lets a traveller wire their own bot so Journava pings them when a background trip
plan finishes (they can fire a plan, walk away, and get told when it's ready).

Credentials live in the vault under provider ``telegram``: the bot token is the
secret, the chat id is an extra field. Sends via the Bot HTTP API:
``https://api.telegram.org/bot<token>/sendMessage``.
"""

from __future__ import annotations

import logging

import httpx

from app.core import vault

logger = logging.getLogger(__name__)
_TIMEOUT = httpx.Timeout(12.0)


def _url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


async def _creds() -> tuple[str, str] | None:
    resolved = await vault.resolve("telegram")
    if not resolved:
        return None
    token = resolved.get("secret")
    chat_id = (resolved.get("extra") or {}).get("chat_id")
    if not token or not chat_id:
        return None
    return str(token), str(chat_id)


async def send(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """Send one message. Returns (ok, human-readable detail)."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                _url(token, "sendMessage"),
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code == 200 and data.get("ok"):
            return True, "Message delivered"
        detail = data.get("description") or f"HTTP {response.status_code}"
        # The two most common setup mistakes, made friendly.
        if "chat not found" in detail.lower():
            detail = "Chat not found — send your bot a message first, then use the chat id from @userinfobot."
        elif "unauthorized" in detail.lower():
            detail = "Bot token rejected — check the token from @BotFather."
        return False, detail
    except httpx.RequestError as exc:
        return False, f"Could not reach Telegram: {exc}"


async def notify(text: str) -> bool:
    """Send using the stored credentials. No-op (False) when not configured."""
    creds = await _creds()
    if creds is None:
        return False
    token, chat_id = creds
    ok, detail = await send(token, chat_id, text)
    if not ok:
        logger.info("Telegram notify failed: %s", detail)
    return ok


async def configured() -> bool:
    return (await _creds()) is not None
