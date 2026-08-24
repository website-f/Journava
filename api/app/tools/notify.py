"""Unified notification fan-out — one call reaches every connected channel.

Today: Telegram + Gmail (email). Callers (reminders, trip countdowns, price-drop
alerts, disruption alerts) call broadcast() and don't care which channels the
traveller connected. Best-effort: a dead channel is logged, never raised.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("journava")


async def broadcast(text: str, *, subject: str = "Journava") -> dict[str, Any]:
    """Send the same message to every connected channel. The text may contain the
    light HTML (<b>, <br>) we use for Telegram; email renders it as HTML."""
    from app.tools import email, telegram

    result: dict[str, Any] = {}
    try:
        result["telegram"] = await telegram.notify(text)
    except Exception as exc:  # noqa: BLE001
        logger.info("broadcast telegram failed: %s", exc)
        result["telegram"] = False
    try:
        result["email"] = await email.notify(subject, text)
    except Exception as exc:  # noqa: BLE001
        logger.info("broadcast email failed: %s", exc)
        result["email"] = False
    return result
