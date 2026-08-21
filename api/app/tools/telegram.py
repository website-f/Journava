"""Telegram Bot notifications.

Lets a traveller wire one or more bots so Journava pings them when a background
trip plan finishes. Bots live in the `notification_bots` table (see
`app.core.bots`), each independently toggleable; a notification fans out to every
enabled bot. Sends via the Bot HTTP API:
``https://api.telegram.org/bot<token>/sendMessage``.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)
_TIMEOUT = httpx.Timeout(12.0)


def _url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


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


async def send_document(
    token: str, chat_id: str, data: bytes, filename: str, caption: str = ""
) -> tuple[bool, str]:
    """Send a file (e.g. a trip PDF) to a chat via sendDocument (multipart)."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.post(
                _url(token, "sendDocument"),
                data={"chat_id": chat_id, "caption": caption[:1000], "parse_mode": "HTML"},
                files={"document": (filename, data, "application/pdf")},
            )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 200 and body.get("ok"):
            return True, "Document delivered"
        return False, body.get("description") or f"HTTP {response.status_code}"
    except httpx.RequestError as exc:
        return False, f"Could not reach Telegram: {exc}"


async def deliver_document(
    chat_id: str, data: bytes, filename: str, caption: str = ""
) -> tuple[bool, str]:
    """Send a document to a specific chat using the org's first enabled bot."""
    from app.core import bots

    targets = await bots.enabled_targets()
    if not targets:
        return False, "No Telegram bot connected — add one under Integrate."
    token = targets[0][0]
    return await send_document(token, chat_id, data, filename, caption)


async def notify(text: str) -> bool:
    """Fan out to every enabled bot. Returns True if at least one delivered."""
    from app.core import bots

    targets = await bots.enabled_targets()
    sent = 0
    for token, chat_id, label in targets:
        ok, detail = await send(token, chat_id, text)
        if ok:
            sent += 1
        else:
            logger.info("Telegram notify failed for %s: %s", label, detail)
    return sent > 0


async def configured() -> bool:
    from app.core import bots

    return bool(await bots.enabled_targets())
