"""Email notifications over Gmail SMTP.

Each enabled email channel (stored in notification_bots with platform='email')
holds a Gmail address + a Google **app password** (not the account password) and
a recipient. We send HTML mail via smtplib over STARTTLS. smtplib is blocking,
so every send runs in a thread so the event loop is never stalled.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger("journava")

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


def _strip_html(text: str) -> str:
    """A plain-text fallback part from the light HTML we use in notifications."""
    import re

    t = re.sub(r"<br\s*/?>", "\n", text)
    t = re.sub(r"<[^>]+>", "", t)
    return t.strip()


def _send_blocking(sender: str, password: str, recipient: str, subject: str, html: str) -> tuple[bool, str]:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(_strip_html(html))
    msg.add_alternative(f"<div style='font-family:system-ui,sans-serif'>{html}</div>", subtype="html")
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
            server.starttls(context=ctx)
            server.login(sender, password)
            server.send_message(msg)
        return True, "sent"
    except smtplib.SMTPAuthenticationError:
        return False, "Gmail rejected the login — use a 16-char App Password (not your account password), with 2FA on."
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def send_one(sender: str, password: str, recipient: str, subject: str, html: str) -> tuple[bool, str]:
    """Send a single email off the event loop. Returns (ok, detail)."""
    return await asyncio.to_thread(_send_blocking, sender, password, recipient, subject, html)


async def notify(subject: str, html: str) -> bool:
    """Fan out to every enabled email channel. True if at least one delivered."""
    from app.core import bots

    targets = await bots.email_targets()
    sent = 0
    for sender, password, recipient in targets:
        ok, detail = await send_one(sender, password, recipient, subject, html)
        if ok:
            sent += 1
        else:
            logger.info("email notify failed for %s: %s", sender, detail)
    return sent > 0


async def configured() -> bool:
    from app.core import bots

    return bool(await bots.email_targets())
