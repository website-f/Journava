"""Knowledge base — the findings the agents document from every plan.

Two jobs:

1. **Write.** After a plan runs, `record_from_plan` mines the results into durable,
   categorised notes ("Hotel prices in Tokyo", "Entry rules for Australia",
   "Where to eat in Osaka"). Re-observing a fact bumps its `seen_count` instead of
   duplicating, so confidence grows with repetition.
2. **Read.** The Research page renders these grouped by category (a growing
   travel library), and `recall(destination)` feeds relevant notes back into the
   agents' prompts so the next plan is smarter.

Postgres-backed, with an in-process fallback so a bare demo still works.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core import db

logger = logging.getLogger(__name__)

CATEGORIES = (
    "flights", "hotels", "food", "activities", "visa",
    "weather", "safety", "budget", "transport", "general",
)

_COLS = "id, category, destination, title, body, tags, confidence, source, seen_count, created_at, updated_at"
_memory: dict[str, dict[str, Any]] = {}


def _dedup_key(category: str, destination: str | None, title: str) -> str:
    return f"{category}|{(destination or '').lower()}|{title.lower()}"[:400]


def _public(row: dict[str, Any]) -> dict[str, Any]:
    created = row.get("updated_at") or row.get("created_at")
    return {
        "id": str(row["id"]),
        "category": row.get("category"),
        "destination": row.get("destination"),
        "title": row.get("title"),
        "body": row.get("body"),
        "tags": list(row.get("tags") or []),
        "confidence": row.get("confidence", "observed"),
        "source": row.get("source"),
        "seen_count": row.get("seen_count", 1),
        "updated_at": created.isoformat() if hasattr(created, "isoformat") else created,
    }


async def record(
    category: str,
    title: str,
    body: str,
    *,
    destination: str | None = None,
    tags: tuple[str, ...] = (),
    confidence: str = "observed",
    source: str | None = None,
) -> None:
    """Upsert a finding. Never raises — documenting is best-effort."""
    if not title or not body:
        return
    key = _dedup_key(category, destination, title)
    pool = await db.get_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO knowledge_notes
                           (dedup_key, category, destination, title, body, tags, confidence, source)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                       ON CONFLICT (dedup_key) DO UPDATE SET
                           body = EXCLUDED.body,
                           tags = EXCLUDED.tags,
                           confidence = EXCLUDED.confidence,
                           source = EXCLUDED.source,
                           seen_count = knowledge_notes.seen_count + 1,
                           updated_at = now()""",
                    key, category, destination, title[:200], body[:2000], list(tags), confidence, source,
                )
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug("knowledge.record db miss: %s", exc)
    existing = _memory.get(key)
    _memory[key] = {
        "id": existing.get("id") if existing else uuid.uuid4(),
        "category": category, "destination": destination, "title": title[:200],
        "body": body[:2000], "tags": list(tags), "confidence": confidence, "source": source,
        "seen_count": (existing.get("seen_count", 1) + 1) if existing else 1,
        "created_at": existing.get("created_at") if existing else datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


async def list_notes(
    category: str | None = None,
    destination: str | None = None,
    limit: int = 300,
) -> list[dict[str, Any]]:
    pool = await db.get_pool()
    if pool is not None:
        try:
            clauses, params = [], []
            if category:
                params.append(category)
                clauses.append(f"category = ${len(params)}")
            if destination:
                params.append(f"%{destination.lower()}%")
                clauses.append(f"lower(destination) LIKE ${len(params)}")
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT {_COLS} FROM knowledge_notes {where} "  # noqa: S608
                    f"ORDER BY updated_at DESC LIMIT ${len(params)}",
                    *params,
                )
            return [_public(dict(r)) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("knowledge.list_notes db miss: %s", exc)
    notes = list(_memory.values())
    if category:
        notes = [n for n in notes if n.get("category") == category]
    if destination:
        notes = [n for n in notes if destination.lower() in (n.get("destination") or "").lower()]
    notes.sort(key=lambda n: n.get("updated_at") or 0, reverse=True)
    return [_public(n) for n in notes[:limit]]


async def grouped() -> dict[str, list[dict[str, Any]]]:
    """All notes bucketed by category, in the display order of CATEGORIES."""
    notes = await list_notes(limit=500)
    out: dict[str, list[dict[str, Any]]] = {c: [] for c in CATEGORIES}
    for note in notes:
        out.setdefault(note["category"] or "general", []).append(note)
    return {cat: items for cat, items in out.items() if items}


async def recall(destination: str | None, limit: int = 8) -> list[dict[str, Any]]:
    """Relevant notes for a destination — fed back into agent prompts."""
    if not destination:
        return []
    return await list_notes(destination=destination, limit=limit)


async def recall_text(destination: str | None, limit: int = 8) -> str:
    """A compact block of prior findings for injecting into an LLM prompt."""
    notes = await recall(destination, limit=limit)
    if not notes:
        return ""
    lines = [f"- ({n['category']}) {n['title']}: {n['body'][:180]}" for n in notes]
    return "WHAT JOURNAVA HAS LEARNED BEFORE:\n" + "\n".join(lines)


# --------------------------------------------------------------------------- #
# Mining a completed plan into notes
# --------------------------------------------------------------------------- #


async def record_from_plan(results: dict[str, Any]) -> None:
    """Extract durable findings from a finished plan. Best-effort, never raises."""
    try:
        chief = (results.get("chief") or {}).get("data") or {}
        destination = chief.get("destination")
        if not destination:
            return
        await _mine_visa(results, destination)
        await _mine_hotels(results, destination)
        await _mine_flights(results, destination)
        await _mine_research(results, destination)
        await _mine_weather(results, destination)
        await _mine_safety(results, destination)
    except Exception as exc:  # noqa: BLE001 — documenting must not affect the plan
        logger.debug("knowledge.record_from_plan failed: %s", exc)


async def _mine_visa(results: dict[str, Any], dest: str) -> None:
    visa = (results.get("visa") or {}).get("data") or {}
    if not visa:
        return
    required = visa.get("visa_required")
    if required is None:
        return
    vtype = visa.get("visa_type") or "unknown"
    docs = ", ".join(visa.get("documents") or []) or "standard travel documents"
    body = (
        f"{'Visa required' if required else 'Visa-free'} ({vtype}). Documents: {docs}."
        + (f" Processing: {visa.get('processing_time')}." if visa.get("processing_time") else "")
    )
    await record("visa", f"Entry rules for {dest}", body, destination=dest, source="visa agent",
                 confidence="observed", tags=("visa", "entry"))


async def _mine_hotels(results: dict[str, Any], dest: str) -> None:
    options = (results.get("hotel") or {}).get("options") or []
    priced = [float(o["price_amount"]) for o in options if o.get("price_amount")]
    if not priced:
        return
    lo, hi = min(priced), max(priced)
    currency = next((o.get("price_currency") for o in options if o.get("price_currency")), "MYR")
    names = ", ".join(o.get("title", "") for o in options[:3] if o.get("title"))
    level = "premium" if lo > 800 else "mid-range" if lo > 300 else "budget-friendly"
    body = f"Stays run about {currency} {lo:,.0f}–{hi:,.0f}/night ({level}). e.g. {names}."
    await record("hotels", f"Hotel prices in {dest}", body, destination=dest, source="hotel agent",
                 tags=("hotels", "price"))


async def _mine_flights(results: dict[str, Any], dest: str) -> None:
    options = (results.get("flight") or {}).get("options") or []
    priced = [float(o["price_amount"]) for o in options if o.get("price_amount")]
    if not priced:
        return
    lo, hi = min(priced), max(priced)
    currency = next((o.get("price_currency") for o in options if o.get("price_currency")), "MYR")
    route = ((results.get("flight") or {}).get("data") or {}).get("route") or {}
    origin = route.get("origin") or "your origin"
    body = f"Fares {origin} → {dest} range about {currency} {lo:,.0f}–{hi:,.0f} (one-way, observed)."
    await record("flights", f"Flight prices to {dest}", body, destination=dest, source="flight agent",
                 tags=("flights", "price"))


async def _mine_research(results: dict[str, Any], dest: str) -> None:
    data = (results.get("research") or {}).get("data") or {}
    attractions = data.get("attractions") or []
    if attractions:
        picks = "; ".join(a.get("title", "") for a in attractions[:5] if a.get("title"))
        if picks:
            await record("activities", f"Top places to visit in {dest}", f"Highlights: {picks}.",
                         destination=dest, source="research agent", tags=("activities",))
    dining = data.get("dining") or []
    if dining:
        picks = "; ".join(d.get("title", "") for d in dining[:5] if d.get("title"))
        if picks:
            await record("food", f"Where to eat in {dest}", f"Notable picks: {picks}.",
                         destination=dest, source="research agent", tags=("food",))
    sentiment = data.get("sentiment_summary")
    if sentiment:
        await record("general", f"Traveller sentiment for {dest}", str(sentiment)[:400],
                     destination=dest, source="research agent", tags=("sentiment",))


async def _mine_weather(results: dict[str, Any], dest: str) -> None:
    weather = (results.get("weather_risk") or {}).get("summary")
    if weather:
        await record("weather", f"Weather in {dest}", str(weather)[:400], destination=dest,
                     source="weather agent", tags=("weather",))


async def _mine_safety(results: dict[str, Any], dest: str) -> None:
    risk = (results.get("risk_advisory") or {})
    summary = risk.get("summary")
    data = risk.get("data") or {}
    level = data.get("safety_level")
    if summary:
        body = (f"Safety level: {level}. " if level else "") + str(summary)[:380]
        await record("safety", f"Safety in {dest}", body, destination=dest,
                     source="risk agent", tags=("safety",))
