"""WhatsApp delivery via the Meta WhatsApp Cloud API.

Same shape as tools/telegram so client delivery can pick a channel. When
credentials aren't configured it returns a labelled "not configured" — the
delivery flow then falls back to Telegram + the interactive share link. Sending
a document over WhatsApp Cloud API needs a hosted media URL, so here we send the
message text + the share link (the link is the PDF's home); wire real media
upload once a public asset host is available.
"""

from __future__ import annotations

import logging

import httpx

from app.core.settings import settings

logger = logging.getLogger("journava")
_TIMEOUT = httpx.Timeout(15.0)


def configured() -> bool:
    return bool(settings.whatsapp_token and settings.whatsapp_phone_id)


async def send_text(to: str, text: str) -> tuple[bool, str]:
    """Send a plain-text WhatsApp message. Returns (ok, detail)."""
    if not configured():
        return False, "WhatsApp not configured (set WHATSAPP_TOKEN + WHATSAPP_PHONE_ID)."
    url = f"https://graph.facebook.com/v20.0/{settings.whatsapp_phone_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"preview_url": True, "body": text[:4000]},
                },
            )
        if 200 <= resp.status_code < 300:
            return True, "WhatsApp message sent"
        try:
            detail = resp.json().get("error", {}).get("message") or f"HTTP {resp.status_code}"
        except ValueError:
            detail = f"HTTP {resp.status_code}"
        return False, detail
    except httpx.RequestError as exc:
        return False, f"Could not reach WhatsApp: {exc}"
