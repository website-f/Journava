"""Trip comparison — put a few planned trips side by side and let an agent (or
the traveller) weigh them: cheapest, safest, best for a given month, and so on.

The compare "cart" itself lives client-side (the ids the traveller ticked); this
module does the two things the client can't: pull the accessible snapshots and
distil each into the handful of comparable facts, and answer a natural-language
comparison question over them with the LLM.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core import db, llm
from app.core.settings import settings

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/compare", tags=["compare"])


class CompareRequest(BaseModel):
    saved_ids: list[str]
    question: str | None = None


def _uid(request: Request) -> str | None:
    return (getattr(request.state, "auth", {}) or {}).get("sub")


def _cheapest(options: list[dict[str, Any]]) -> dict[str, Any] | None:
    priced = []
    for o in options or []:
        amt = o.get("price_amount")
        try:
            if amt is not None and float(amt) > 0:
                priced.append((float(amt), o))
        except (TypeError, ValueError):
            continue
    if not priced:
        return None
    amount, opt = min(priced, key=lambda p: p[0])
    return {
        "title": opt.get("title"),
        "price_amount": amount,
        "price_currency": opt.get("price_currency") or "MYR",
        "bookable": bool(opt.get("bookable")),
    }


def summarize_trip(saved_id: str, title: str, destination: str | None, snap: dict[str, Any]) -> dict[str, Any]:
    """The comparable facts of one plan — kept small and structured so several
    fit in one prompt and render in one table."""
    chief = (snap.get("chief") or {}).get("data") or {}
    budget = (snap.get("budget") or {}).get("data") or {}
    wr = snap.get("weather_risk") or {}
    wr_data = wr.get("data") or {}
    research = (snap.get("research") or {}).get("data") or {}
    flight = _cheapest(((snap.get("flight") or {}).get("options")) or [])
    hotel = _cheapest(((snap.get("hotel") or {}).get("options")) or [])
    attractions = [
        o.get("title")
        for o in ((snap.get("research") or {}).get("options") or [])
        if o.get("kind") == "activity"
    ][:5]
    social = research.get("social_signal") or {}

    return {
        "saved_id": saved_id,
        "destination": destination or chief.get("destination") or title,
        "dates": {
            "start": chief.get("start_date"),
            "end": chief.get("end_date"),
            "days": chief.get("duration_days"),
        },
        "travellers": chief.get("travellers"),
        "budget": {
            "planned": budget.get("budget_amount"),
            "estimated_spend": budget.get("spent_estimate"),
            "currency": budget.get("currency") or chief.get("budget_currency") or "MYR",
            "over_budget": budget.get("over_budget"),
        },
        "cheapest_flight": flight,
        "cheapest_hotel": hotel,
        "risk_level": wr_data.get("risk_level"),
        "weather": wr.get("summary"),
        "social_score": social.get("score"),
        "top_attractions": attractions,
    }


async def _load(ids: list[str], uid: str | None) -> list[dict[str, Any]]:
    pool = await db.get_pool()
    if pool is None or not ids:
        return []
    try:
        uuids = [uuid.UUID(i) for i in ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid trip id in the comparison.") from None
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT s.id, s.title, s.destination, s.snapshot
                   FROM saved_results s
                   LEFT JOIN trip_collaborators c
                          ON c.saved_id = s.id AND c.user_id = $2
                   WHERE s.id = ANY($1)
                     AND ($2::uuid IS NULL OR s.user_id = $2 OR c.user_id IS NOT NULL)""",
                uuids,
                uuid.UUID(uid) if uid else None,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("compare load failed: %s", exc)
        return []
    # Preserve the caller's order.
    by_id = {str(r["id"]): r for r in rows}
    out: list[dict[str, Any]] = []
    for i in ids:
        r = by_id.get(i)
        if not r:
            continue
        snap = r["snapshot"]
        snap = json.loads(snap) if isinstance(snap, str) else (snap or {})
        out.append(summarize_trip(str(r["id"]), r["title"], r["destination"], snap))
    return out


_SYSTEM = (
    "You compare travel plans for a traveller and answer their question honestly "
    "and concisely. Lead with a clear recommendation, then 2-4 sentences of why, "
    "citing the actual numbers (prices, risk, dates) from the data. If a plan is "
    "missing data for what they asked, say so rather than guessing. Plain text, "
    "no markdown headers."
)


@router.post("/analyze")
async def analyze(body: CompareRequest, request: Request) -> dict[str, Any]:
    """Summarise the compared trips and answer a comparison question about them."""
    trips = await _load(body.saved_ids, _uid(request))
    if len(trips) < 2:
        return {
            "trips": trips,
            "answer": "Add at least two trips to compare them.",
        }

    question = (body.question or "Which of these is the best overall choice, and why?").strip()
    user = (
        f"The traveller asks: {question}\n\n"
        f"Here are the plans as JSON:\n{json.dumps(trips, default=str, ensure_ascii=False)}"
    )
    try:
        answer = await llm.complete(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            agent="compare",
        )
    except Exception as exc:  # noqa: BLE001 — never 500 the compare page
        logger.warning("compare analyze LLM failed: %s", exc)
        answer = (
            "I couldn't reach the comparison model just now — but the table shows the "
            "key numbers side by side so you can weigh them directly."
        )
    return {"trips": trips, "answer": answer.strip(), "question": question}


@router.post("/summaries")
async def summaries(body: CompareRequest, request: Request) -> dict[str, Any]:
    """Just the structured side-by-side facts (no LLM) — powers the table."""
    return {"trips": await _load(body.saved_ids, _uid(request))}
