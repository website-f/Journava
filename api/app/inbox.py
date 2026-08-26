"""Inbound leads — a real WhatsApp webhook + an AI auto-reply, so an enquiry
becomes a qualified lead with zero manual work.

An incoming message is stored, answered by an AI qualifier (reusing the org's
own Agent-Studio "customer reply" agent if it has one, else a sensible default),
the reply is sent back over the channel, and the sender is captured as a lead in
the agency's client list. The Meta webhook is production-real; a console
"simulate" endpoint drives the exact same handler so it demos without a live
number.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.auth.deps import require_agency
from app.core import db, llm
from app.core.settings import settings
from app.tools import whatsapp

logger = logging.getLogger("journava")

config_router = APIRouter(prefix=f"{settings.api_prefix}/agency", tags=["inbox"])
webhook_router = APIRouter(prefix=f"{settings.api_prefix}/webhooks", tags=["webhooks"])

_DEFAULT_QUALIFIER = (
    "You are a warm, efficient lead qualifier for a travel business. A prospective "
    "client has messaged. Reply in 2-4 short sentences: acknowledge what they want, "
    "ask the ONE or TWO most useful qualifying questions (destination, dates, budget, "
    "party size — whichever they haven't given), and invite them to say more. Friendly, "
    "professional, no markdown."
)


async def _qualifier_prompt(org_id: str) -> str:
    """Use the org's own Agent-Studio 'customer reply' agent if it built one —
    so the Inbox speaks in the voice they designed — else a default."""
    pool = await db.get_pool()
    if pool is None:
        return _DEFAULT_QUALIFIER
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT system_prompt FROM custom_agents "
                "WHERE org_id = $1 AND tools::text LIKE '%customer_reply%' "
                "ORDER BY created_at DESC LIMIT 1",
                org_id,
            )
        if row and row["system_prompt"]:
            return row["system_prompt"] + "\n\nKeep replies to 2-4 short sentences; ask the key qualifying questions."
    except Exception as exc:  # noqa: BLE001
        logger.debug("qualifier lookup failed: %s", exc)
    return _DEFAULT_QUALIFIER


async def _log(org_id: str, channel: str, sender: str, name: str | None, text: str, direction: str) -> None:
    pool = await db.get_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO inbox_messages (org_id, channel, sender, sender_name, text, direction) "
                "VALUES ($1,$2,$3,$4,$5,$6)",
                org_id, channel, sender, name, text, direction,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("inbox log failed: %s", exc)


async def _capture_lead(org_id: str, channel: str, sender: str, name: str | None, text: str) -> None:
    """First message from a sender → create an agency_clients lead."""
    pool = await db.get_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM agency_clients WHERE org_id = $1 AND whatsapp = $2 LIMIT 1",
                uuid.UUID(org_id), sender,
            )
            if not exists:
                await conn.execute(
                    """INSERT INTO agency_clients (org_id, name, whatsapp, channel, source, notes)
                       VALUES ($1,$2,$3,$4,'whatsapp_inbound',$5)""",
                    uuid.UUID(org_id), name or f"WhatsApp {sender[-4:]}", sender, channel, text[:280],
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("lead capture failed: %s", exc)


async def handle_inbound(org_id: str, channel: str, sender: str, name: str | None, text: str) -> dict[str, Any]:
    """Store the message, generate + send an AI reply, capture the lead."""
    await _log(org_id, channel, sender, name, text, "in")
    await _capture_lead(org_id, channel, sender, name, text)

    system = await _qualifier_prompt(org_id)
    # Ground the reply in the business's Knowledge Base so it answers accurately.
    try:
        from app.kb import kb_context

        facts = await kb_context(org_id, text)
        if facts:
            system += "\n\nYour business's own facts (use these when relevant):\n" + facts
    except Exception as exc:  # noqa: BLE001
        logger.debug("inbox kb inject failed: %s", exc)
    try:
        reply = (await llm.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": text}],
            agent="inbox-qualifier",
        )).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("inbox AI reply failed: %s", exc)
        reply = "Thanks for reaching out! Could you tell me your destination, rough dates and party size so I can put together some options?"

    sent = False
    if channel == "whatsapp" and whatsapp.configured():
        try:
            sent, _ = await whatsapp.send_text(sender, reply)
        except Exception as exc:  # noqa: BLE001
            logger.info("whatsapp send failed: %s", exc)
    await _log(org_id, channel, sender, name, reply, "out")
    return {"reply": reply, "sent": sent}


# --------------------------------------------------------------------------- #
# Public Meta webhook (verify handshake + incoming messages)
# --------------------------------------------------------------------------- #


@webhook_router.get("/whatsapp")
async def whatsapp_verify(request: Request) -> PlainTextResponse:
    """Meta subscription handshake: echo hub.challenge when the token matches."""
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == settings.whatsapp_verify_token:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("forbidden", status_code=403)


@webhook_router.post("/whatsapp")
async def whatsapp_inbound(request: Request) -> dict[str, Any]:
    """Incoming WhatsApp messages → AI-qualified + captured as leads."""
    org_id = settings.whatsapp_org_id
    if not org_id:
        # No routing org configured — acknowledge so Meta doesn't retry.
        return {"ok": True, "note": "no org routed"}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {"ok": True}
    handled = 0
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            contacts = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue
                sender = msg.get("from", "")
                text = (msg.get("text") or {}).get("body", "")
                if sender and text:
                    await handle_inbound(org_id, "whatsapp", sender, contacts.get(sender), text)
                    handled += 1
    return {"ok": True, "handled": handled}


# --------------------------------------------------------------------------- #
# Console (authed): the inbox + a simulate path for demos
# --------------------------------------------------------------------------- #


class SimulateIn(BaseModel):
    sender: str = "60123456789"
    name: str | None = None
    text: str


@config_router.get("/inbox")
async def get_inbox(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    """Conversations grouped by sender, newest thread first."""
    pool = await db.get_pool()
    if pool is None:
        return {"threads": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT channel, sender, sender_name, text, direction, created_at "
            "FROM inbox_messages WHERE org_id = $1 ORDER BY created_at",
            agency["org_id"],
        )
    threads: dict[str, dict[str, Any]] = {}
    for r in rows:
        t = threads.setdefault(r["sender"], {
            "sender": r["sender"], "name": r["sender_name"], "channel": r["channel"], "messages": [],
        })
        t["messages"].append({"text": r["text"], "direction": r["direction"], "at": r["created_at"].isoformat()})
    ordered = sorted(threads.values(), key=lambda t: t["messages"][-1]["at"], reverse=True)
    return {"threads": ordered}


@config_router.post("/inbox/simulate")
async def simulate_inbound(body: SimulateIn, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    """Feed a message through the real inbound handler (for demos without a live
    WhatsApp number). Scopes to the caller's org."""
    result = await handle_inbound(agency["org_id"], "whatsapp", body.sender, body.name, body.text)
    return result
