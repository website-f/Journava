"""Autonomous Boardroom — the org's agents convene on their own.

Where Agent Teams chains agents on a brief you type, the Boardroom is a standing
meeting the business's agents hold by themselves: built-in Revenue / Bookings /
Marketing leads plus every custom agent you built in Agent Studio (add as many
skills as you like — they all get a seat). They each speak to the org's REAL
numbers, then a Chair synthesises decisions, action items, and a ready-to-post
marketing message. Flip on Autopilot and it convenes on the schedule, unattended,
within this org's scope only. No real money or sends — drafts and decisions.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.auth.deps import resolve_org_id
from app.core import db, llm
from app.core.settings import settings
from app.supplier import store as supplier_store

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/boardroom", tags=["boardroom"])

_MAX_SEATS = 6  # bound cost/latency: built-in leads + a few custom agents

# The three built-in executives so the room is useful even with zero custom agents.
_BUILTIN = [
    {"name": "Revenue Strategist", "emoji": "💰", "role": "revenue",
     "persona": "You are a hotel Revenue Strategist. You care about occupancy, average rate, "
                "yield and beating the OTAs on direct margin. Propose ONE concrete revenue move."},
    {"name": "Bookings Manager", "emoji": "🛎️", "role": "bookings",
     "persona": "You are a Bookings/Front-Office Manager. You care about filling rooms, guest "
                "experience, reducing no-shows and handling reservations smoothly. Propose ONE concrete booking move."},
    {"name": "Marketing Lead", "emoji": "📣", "role": "marketing",
     "persona": "You are a Marketing Lead for a direct-booking hotel. You care about demand gen "
                "across social + email + the direct site. Propose ONE concrete marketing move."},
]

_DEFAULT_TOPIC = "How do we grow revenue this week, keep bookings healthy, and market ourselves — given our real numbers?"


class SettingsBody(BaseModel):
    enabled: bool | None = None
    focus: str | None = None


class ConveneBody(BaseModel):
    topic: str | None = None


async def _org(request: Request) -> str:
    return await resolve_org_id(request)


async def _get_settings(org_id: str) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"enabled": False, "focus": None}
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM boardroom_settings WHERE org_id = $1", uuid.UUID(org_id))
        if row is None:
            row = await conn.fetchrow(
                "INSERT INTO boardroom_settings (org_id) VALUES ($1) RETURNING *", uuid.UUID(org_id)
            )
    return {"enabled": row["enabled"], "focus": row.get("focus")}


async def _org_brief(org_id: str) -> str:
    """A compact, real snapshot the agents reason over — never invented numbers."""
    properties = await supplier_store.list_properties(org_id)
    rooms = [l for p in properties for l in (p.get("listings") or [])]
    prices = [float(l["price_amount"]) for l in rooms if l.get("price_amount")]
    cities = sorted({(p.get("city") or "").strip() for p in properties if p.get("city")})
    avg = round(sum(prices) / len(prices)) if prices else None
    bookings = revenue = 0
    cur = "MYR"
    recent_moves: list[str] = []
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                b = await conn.fetchrow(
                    "SELECT count(*) n, COALESCE(SUM(amount),0) rev, MAX(currency) cur "
                    "FROM hotel_bookings WHERE org_id = $1 AND status <> 'cancelled'",
                    uuid.UUID(org_id),
                )
                adj = await conn.fetch(
                    "SELECT room_title, delta_pct, applied FROM price_adjustments "
                    "WHERE org_id = $1 ORDER BY created_at DESC LIMIT 4",
                    uuid.UUID(org_id),
                )
            bookings, revenue, cur = int(b["n"] or 0), round(float(b["rev"] or 0)), b["cur"] or "MYR"
            recent_moves = [
                f"{r['room_title']} {'+' if (r['delta_pct'] or 0) > 0 else ''}{r['delta_pct']}%"
                f"{' (applied)' if r['applied'] else ''}"
                for r in adj if r["delta_pct"]
            ]
        except Exception as exc:  # noqa: BLE001
            logger.info("boardroom brief skipped: %s", exc)
    return (
        f"Live rooms: {len(rooms)}; avg nightly rate: {cur} {avg}; cities: {', '.join(cities) or 'n/a'}. "
        f"Active bookings: {bookings} worth {cur} {revenue}. "
        f"Recent autopilot price moves: {', '.join(recent_moves) or 'none yet'}."
    )


async def _participants(org_id: str) -> list[dict[str, Any]]:
    """Built-in executives + the org's custom agents (all of them get a seat)."""
    seats = [dict(b) for b in _BUILTIN]
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                # custom_agents.org_id is TEXT (Agent Studio binds the raw org id),
                # unlike our UUID-typed boardroom tables — pass the string here.
                rows = await conn.fetch(
                    "SELECT name, emoji, role, system_prompt FROM custom_agents WHERE org_id = $1 ORDER BY created_at",
                    org_id,
                )
            for r in rows:
                seats.append({
                    "name": r["name"], "emoji": r["emoji"] or "🤖",
                    "role": "custom", "persona": r["system_prompt"],
                })
        except Exception as exc:  # noqa: BLE001
            logger.info("boardroom participants skipped: %s", exc)
    return seats[:_MAX_SEATS]


_CHAIR_SYSTEM = """You are the Chair of a hotel's autonomous boardroom. You are given \
the business's real numbers and each executive's opening proposal. Synthesise the \
meeting: resolve overlaps, keep only what's realistic for a small direct-booking \
hotel, and turn talk into action.

Respond ONLY as JSON:
{"summary": "2-3 sentence readout of what the room decided",
 "decisions": ["short decision", ...2-4],
 "action_items": [{"owner": "which exec/role", "action": "concrete next step"} ...3-5],
 "marketing_draft": "a ready-to-post promo message (2-4 sentences, ready to send on social/email/WhatsApp)"}"""


async def convene(org_id: str, topic: str | None = None) -> dict[str, Any]:
    """Run one meeting: opening statements from every seat, then a Chair synthesis.
    Persists the minutes and returns them."""
    cfg = await _get_settings(org_id)
    the_topic = (topic or "").strip() or (cfg.get("focus") or "").strip() or _DEFAULT_TOPIC
    brief = await _org_brief(org_id)
    seats = await _participants(org_id)

    transcript: list[dict[str, Any]] = []
    for seat in seats:
        system = (
            seat["persona"]
            + "\n\nYou are in a live boardroom meeting for this business. Speak in the FIRST person, "
            "2-3 sentences, grounded in the real numbers below. End with ONE concrete proposal. "
            "Plain text, no markdown."
            + f"\n\nBusiness snapshot: {brief}"
        )
        try:
            text = await llm.complete(
                [{"role": "system", "content": system}, {"role": "user", "content": f"Meeting topic: {the_topic}"}],
                agent=f"boardroom:{seat['role']}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("boardroom seat %s failed: %s", seat["name"], exc)
            continue
        transcript.append({"speaker": seat["name"], "emoji": seat["emoji"], "role": seat["role"], "text": text.strip()})

    minutes: dict[str, Any] = {"summary": "", "decisions": [], "action_items": [], "marketing_draft": ""}
    if transcript:
        convo = "\n\n".join(f"{t['speaker']} ({t['role']}): {t['text']}" for t in transcript)
        try:
            raw = await llm.complete(
                [
                    {"role": "system", "content": _CHAIR_SYSTEM},
                    {"role": "user", "content": f"Business snapshot: {brief}\n\nTopic: {the_topic}\n\nOpening statements:\n{convo}"},
                ],
                response_format={"type": "json_object"}, agent="boardroom:chair",
            )
            data = json.loads(raw)
            if isinstance(data, dict):
                minutes["summary"] = str(data.get("summary") or "")
                minutes["decisions"] = [str(x) for x in (data.get("decisions") or [])][:4]
                minutes["action_items"] = [
                    {"owner": str(a.get("owner") or "Team"), "action": str(a.get("action") or "")}
                    for a in (data.get("action_items") or []) if isinstance(a, dict)
                ][:5]
                minutes["marketing_draft"] = str(data.get("marketing_draft") or "")
        except Exception as exc:  # noqa: BLE001
            logger.info("boardroom chair failed: %s", exc)

    meeting = {
        "topic": the_topic, "summary": minutes["summary"], "transcript": transcript,
        "decisions": minutes["decisions"], "action_items": minutes["action_items"],
        "marketing_draft": minutes["marketing_draft"],
    }
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO boardroom_meetings
                           (org_id, topic, summary, transcript, decisions, action_items, marketing_draft)
                       VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id, created_at""",
                    uuid.UUID(org_id), the_topic, minutes["summary"],
                    json.dumps(transcript), json.dumps(minutes["decisions"]),
                    json.dumps(minutes["action_items"]), minutes["marketing_draft"],
                )
            meeting["id"] = str(row["id"])
            meeting["created_at"] = row["created_at"].isoformat()
        except Exception as exc:  # noqa: BLE001
            logger.info("boardroom persist skipped: %s", exc)
    return meeting


def _meeting_row(r: dict[str, Any]) -> dict[str, Any]:
    def _j(v: Any, default: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (ValueError, TypeError):
                return default
        return v if v is not None else default
    return {
        "id": str(r["id"]), "topic": r.get("topic"), "summary": r.get("summary"),
        "transcript": _j(r.get("transcript"), []), "decisions": _j(r.get("decisions"), []),
        "action_items": _j(r.get("action_items"), []), "marketing_draft": r.get("marketing_draft"),
        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
    }


@router.get("")
async def get_boardroom(request: Request) -> dict[str, Any]:
    org_id = await _org(request)
    cfg = await _get_settings(org_id)
    seats = await _participants(org_id)
    meetings: list[dict[str, Any]] = []
    pool = await db.get_pool()
    if pool is not None:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM boardroom_meetings WHERE org_id = $1 ORDER BY created_at DESC LIMIT 10",
                uuid.UUID(org_id),
            )
        meetings = [_meeting_row(dict(r)) for r in rows]
    return {
        "settings": cfg,
        "participants": [{"name": s["name"], "emoji": s["emoji"], "role": s["role"]} for s in seats],
        "meetings": meetings,
    }


@router.post("/settings")
async def set_boardroom(body: SettingsBody, request: Request) -> dict[str, Any]:
    org_id = await _org(request)
    await _get_settings(org_id)
    pool = await db.get_pool()
    if pool is not None:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE boardroom_settings SET enabled = COALESCE($2, enabled), "
                "focus = COALESCE($3, focus), updated_at = now() WHERE org_id = $1",
                uuid.UUID(org_id), body.enabled, body.focus,
            )
    return {"settings": await _get_settings(org_id)}


@router.post("/convene")
async def convene_now(body: ConveneBody, request: Request) -> dict[str, Any]:
    org_id = await _org(request)
    meeting = await convene(org_id, body.topic)
    return {"meeting": meeting}


async def run_all_boardrooms() -> None:
    """Periodic autonomous convene for every org that switched Autopilot on."""
    pool = await db.get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT org_id FROM boardroom_settings WHERE enabled")
    for r in rows:
        try:
            await convene(str(r["org_id"]))
        except Exception as exc:  # noqa: BLE001
            logger.info("scheduled boardroom failed for %s: %s", r["org_id"], exc)
