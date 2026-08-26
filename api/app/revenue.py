"""Revenue Autopilot — an always-on yield manager for a hotel's own rooms.

It runs the same yield agent the manual "AI price" button uses (competitor rates
via Camofox + channel occupancy + live demand), but for *every* room, on a
schedule, and — within guardrails the owner sets — moves the price automatically.

Guardrails keep it safe:
- ``max_change_pct`` caps how far a single run can move a price (no wild swings).
- ``floor_pct`` refuses to price below that % of the room's list price.
- ``auto_apply`` off => the sweep only *proposes* (logged, nothing changes).

Every run writes an audit row to ``price_adjustments`` so the owner sees exactly
what the autopilot did and why.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import require_agency
from app.core import db
from app.core.settings import settings
from app.supplier import store as supplier_store
from app.supplier.ai import recommend_price

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/revenue", tags=["revenue-autopilot"])

_DEFAULTS = {"enabled": False, "auto_apply": False, "max_change_pct": 15, "floor_pct": 60}


class Settings(BaseModel):
    enabled: bool | None = None
    auto_apply: bool | None = None
    max_change_pct: int | None = None
    floor_pct: int | None = None


class RunRequest(BaseModel):
    #: Override the stored auto_apply for this run (e.g. a one-click "apply now").
    apply: bool | None = None


async def _get_settings(org_id: str) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"org_id": org_id, **_DEFAULTS}
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM revenue_autopilot WHERE org_id = $1", uuid.UUID(org_id))
        if row is None:
            row = await conn.fetchrow(
                "INSERT INTO revenue_autopilot (org_id) VALUES ($1) RETURNING *", uuid.UUID(org_id)
            )
    d = dict(row)
    return {
        "enabled": d["enabled"], "auto_apply": d["auto_apply"],
        "max_change_pct": d["max_change_pct"], "floor_pct": d["floor_pct"],
    }


@router.get("/autopilot")
async def get_autopilot(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    org_id = agency["org_id"]
    cfg = await _get_settings(org_id)
    properties = await supplier_store.list_properties(org_id)
    rooms = [
        {
            "id": l["id"], "title": l["title"], "property": p["name"],
            "price_amount": l.get("price_amount"), "price_currency": l.get("price_currency") or "MYR",
            "original_price": l.get("original_price"),
        }
        for p in properties for l in (p.get("listings") or [])
    ]
    recent = await _recent_adjustments(org_id)
    return {"settings": cfg, "rooms": rooms, "recent": recent}


@router.post("/autopilot/settings")
async def set_autopilot(body: Settings, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    org_id = agency["org_id"]
    await _get_settings(org_id)  # ensure the row exists
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE revenue_autopilot SET
                   enabled = COALESCE($2, enabled),
                   auto_apply = COALESCE($3, auto_apply),
                   max_change_pct = COALESCE($4, max_change_pct),
                   floor_pct = COALESCE($5, floor_pct),
                   updated_at = now()
               WHERE org_id = $1""",
            uuid.UUID(org_id), body.enabled, body.auto_apply,
            None if body.max_change_pct is None else max(1, min(60, body.max_change_pct)),
            None if body.floor_pct is None else max(10, min(100, body.floor_pct)),
        )
    return {"settings": await _get_settings(org_id)}


@router.post("/autopilot/run")
async def run_autopilot_now(body: RunRequest, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    org_id = agency["org_id"]
    cfg = await _get_settings(org_id)
    apply = cfg["auto_apply"] if body.apply is None else bool(body.apply)
    return await run_autopilot(org_id, cfg, apply=apply)


async def _recent_adjustments(org_id: str, limit: int = 20) -> list[dict[str, Any]]:
    pool = await db.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM price_adjustments WHERE org_id = $1 ORDER BY created_at DESC LIMIT $2",
            uuid.UUID(org_id), limit,
        )
    out = []
    for r in (dict(x) for x in rows):
        out.append({
            "listing_id": str(r["listing_id"]) if r.get("listing_id") else None,
            "room_title": r.get("room_title"),
            "old_price": float(r["old_price"]) if r.get("old_price") is not None else None,
            "new_price": float(r["new_price"]) if r.get("new_price") is not None else None,
            "delta_pct": float(r["delta_pct"]) if r.get("delta_pct") is not None else None,
            "demand_level": r.get("demand_level"),
            "rationale": r.get("rationale"),
            "applied": r.get("applied"),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        })
    return out


def _clamp_price(current: float, recommended: float, list_price: float, max_change_pct: int, floor_pct: int) -> float:
    """Apply the guardrails: cap the per-run move, and never dip below the floor."""
    maxc = max(1, max_change_pct) / 100.0
    lo, hi = current * (1 - maxc), current * (1 + maxc)
    new = min(max(recommended, lo), hi)
    floor = (list_price or current) * (max(10, floor_pct) / 100.0)
    new = max(new, floor)
    return round(new)


async def run_autopilot(org_id: str, cfg: dict[str, Any] | None = None, *, apply: bool) -> dict[str, Any]:
    """Sweep every room: get the yield agent's recommendation, clamp to the
    guardrails, log the adjustment, and (when ``apply``) write the new price."""
    cfg = cfg or await _get_settings(org_id)
    pool = await db.get_pool()
    properties = await supplier_store.list_properties(org_id)
    results: list[dict[str, Any]] = []
    applied_count = 0

    for prop in properties:
        for l in (prop.get("listings") or []):
            current = l.get("price_amount")
            if not current or current <= 0:
                continue
            current = float(current)
            list_price = float(l.get("original_price") or current)
            try:
                rec = await recommend_price(l["id"])
            except Exception as exc:  # noqa: BLE001 — pricing is best-effort per room
                logger.info("autopilot price failed for %s: %s", l["id"], exc)
                continue
            recommended = float(rec.get("recommended_price") or current)
            new_price = _clamp_price(current, recommended, list_price, cfg["max_change_pct"], cfg["floor_pct"])
            delta_pct = round((new_price - current) / current * 100, 1) if current else 0.0
            meaningful = abs(delta_pct) >= 1.0
            did_apply = bool(apply and meaningful)
            if did_apply:
                await supplier_store.update_listing_price(org_id, l["id"], new_price)
                applied_count += 1

            if pool is not None:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO price_adjustments
                               (org_id, listing_id, room_title, old_price, new_price, delta_pct,
                                demand_level, rationale, applied)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                        uuid.UUID(org_id), uuid.UUID(l["id"]), l.get("title"),
                        current, new_price, delta_pct,
                        rec.get("demand_level"), (rec.get("rationale") or "")[:600], did_apply,
                    )
            results.append({
                "listing_id": l["id"], "room_title": l.get("title"),
                "old_price": current, "new_price": new_price, "delta_pct": delta_pct,
                "currency": l.get("price_currency") or "MYR",
                "demand_level": rec.get("demand_level"), "rationale": rec.get("rationale"),
                "applied": did_apply, "held": not meaningful,
            })

    if apply and applied_count:
        try:
            from app.tools import notify

            await notify.broadcast(
                f"📈 <b>Revenue Autopilot</b> adjusted {applied_count} room price(s) "
                f"based on live demand + competitor rates."
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("autopilot notify failed: %s", exc)

    return {"applied": apply, "applied_count": applied_count, "results": results}


async def run_all_autopilots() -> None:
    """Periodic sweep — auto-apply for every org that has it switched on."""
    pool = await db.get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT org_id FROM revenue_autopilot WHERE enabled AND auto_apply")
    for r in rows:
        try:
            await run_autopilot(str(r["org_id"]), apply=True)
        except Exception as exc:  # noqa: BLE001
            logger.info("autopilot sweep failed for %s: %s", r["org_id"], exc)
