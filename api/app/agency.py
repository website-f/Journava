"""Agency / partner console — the B2B surface.

Aggregates the org's managed trips and the OTA commission avoided by booking
direct through Journava's agents. This is the "bypass the OTAs" story: an agency
(or a hotel via the Partner portal) lets the agent mesh search, book and monitor
directly, keeping the ~10% an OTA would take.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth.deps import require_agency, resolve_org_id
from app.brain import history, policy_store
from app.core import db
from app.core.settings import settings
from app.runtime import jobs
from app.runtime.router import PlanJobRequest, _run_plan_job
from app.tools import policy as policy_tools

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/agency", tags=["agency"])


@router.get("/overview")
async def overview(request: Request, limit: int = 15) -> dict[str, Any]:
    """Managed trips + aggregate OTA commission avoided (from flight results)."""
    entries = await history.list_entries(limit=limit)
    trips: list[dict[str, Any]] = []
    total_saved = 0.0
    currency = "MYR"

    for entry in entries:
        saved = 0.0
        try:
            full = await history.get_entry(entry["id"])
            snapshot = (full or {}).get("result_snapshot") or {}
            flight = snapshot.get("flight") or {}
            saved_info = (flight.get("data") or {}).get("commission_saved") or {}
            saved = float(saved_info.get("amount") or 0)
            if saved_info.get("currency"):
                currency = saved_info["currency"]
        except Exception:  # noqa: BLE001 — a bad snapshot must not break the console
            saved = 0.0
        total_saved += saved
        trips.append(
            {
                "id": entry["id"],
                "goal": entry.get("goal"),
                "scope": entry.get("scope"),
                "destination": entry.get("destination"),
                "option_count": entry.get("option_count", 0),
                "created_at": entry.get("created_at"),
                "saved": round(saved, 2),
            }
        )

    return {
        "metrics": {
            "managed_trips": len(trips),
            "total_saved": round(total_saved, 2),
            "currency": currency,
            "commission_rate_pct": 10,
        },
        "trips": trips,
    }


@router.get("/corporate")
async def corporate(request: Request, limit: int = 25) -> dict[str, Any]:
    """Corporate control tower: active policy + compliance, duty-of-care (where
    are our travellers and how risky), and ESG (aggregate carbon)."""
    org_id = await resolve_org_id(request)
    policy_doc = policy_tools.merge(await policy_store.load_policy(org_id))

    entries = await history.list_entries(limit=limit)
    travellers: list[dict[str, Any]] = []
    risk_counts = {"safe": 0, "caution": 0, "dangerous": 0}
    esg = {"total_co2_kg": 0.0, "total_offset_usd": 0.0, "trips_measured": 0}
    policy_violations = 0

    for entry in entries:
        try:
            full = await history.get_entry(entry["id"])
        except Exception:  # noqa: BLE001 — a bad snapshot must not break the console
            continue
        snapshot = (full or {}).get("result_snapshot") or {}
        destination = entry.get("destination") or entry.get("goal") or "Trip"

        risk = (snapshot.get("risk_advisory") or {}).get("data") or {}
        level = str(risk.get("safety_level") or "").lower()
        emergency = (snapshot.get("emergency") or {}).get("data") or {}
        if level or snapshot.get("risk_advisory"):
            if level in risk_counts:
                risk_counts[level] += 1
            travellers.append(
                {
                    "trip_id": entry["id"],
                    "destination": destination,
                    "safety_level": level or "unknown",
                    "advisory": (risk.get("advisory_text") or "")[:220],
                    "embassy_phone": emergency.get("embassy_phone"),
                    "created_at": entry.get("created_at"),
                }
            )

        sus = (snapshot.get("sustainability") or {}).get("data") or {}
        try:
            co2 = float(sus.get("flight_co2_kg") or 0)
            offset = float(sus.get("carbon_offset_usd") or 0)
        except (TypeError, ValueError):
            co2 = offset = 0.0
        if co2 or offset:
            esg["total_co2_kg"] += co2
            esg["total_offset_usd"] += offset
            esg["trips_measured"] += 1

        flight_policy = ((snapshot.get("flight") or {}).get("data") or {}).get("policy") or {}
        policy_violations += len(flight_policy.get("violations") or [])

    return {
        "policy": {"configured": not policy_tools.is_empty(policy_doc), **policy_doc},
        "policy_violations": policy_violations,
        "duty_of_care": {
            "travellers": travellers,
            "risk_counts": risk_counts,
            "at_risk": risk_counts["caution"] + risk_counts["dangerous"],
        },
        "esg": {
            "total_co2_kg": round(esg["total_co2_kg"], 1),
            "total_offset_usd": round(esg["total_offset_usd"], 2),
            "trips_measured": esg["trips_measured"],
        },
    }


# --------------------------------------------------------------------------- #
# Clients: plan a trip FOR a client, compile a PDF, deliver over Telegram      #
# --------------------------------------------------------------------------- #


class ClientCreate(BaseModel):
    name: str
    email: str | None = None
    telegram_chat_id: str | None = None
    notes: str | None = None


class PlanForClient(BaseModel):
    destination: str
    goal: str | None = None
    origin: str | None = None
    start_date: str | None = None


class DeliverRequest(BaseModel):
    client_id: str
    job_id: str


@router.get("/clients")
async def list_clients(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"clients": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, email, telegram_chat_id, notes, created_at FROM agency_clients "
            "WHERE org_id = $1 ORDER BY created_at DESC",
            uuid.UUID(agency["org_id"]),
        )
    return {
        "clients": [
            {
                "id": str(r["id"]), "name": r["name"], "email": r["email"],
                "telegram_chat_id": r["telegram_chat_id"], "notes": r["notes"],
            }
            for r in rows
        ]
    }


@router.post("/clients")
async def create_client(body: ClientCreate, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        return {"error": "database unavailable"}
    async with pool.acquire() as conn:
        cid = await conn.fetchval(
            """INSERT INTO agency_clients (org_id, name, email, telegram_chat_id, notes)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            uuid.UUID(agency["org_id"]), body.name, body.email, body.telegram_chat_id, body.notes,
        )
    return {"id": str(cid), "name": body.name}


@router.delete("/clients/{client_id}")
async def delete_client(client_id: str, agency: dict = Depends(require_agency)) -> dict[str, bool]:
    pool = await db.get_pool()
    if pool is not None:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM agency_clients WHERE id = $1 AND org_id = $2",
                uuid.UUID(client_id), uuid.UUID(agency["org_id"]),
            )
    return {"deleted": True}


async def _get_client(org_id: str, client_id: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, email, telegram_chat_id FROM agency_clients WHERE id = $1 AND org_id = $2",
            uuid.UUID(client_id), uuid.UUID(org_id),
        )
    return dict(row) if row else None


@router.post("/clients/{client_id}/plan")
async def plan_for_client(client_id: str, body: PlanForClient, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    """Build a full package for a client — runs the full_trip mesh in the background."""
    client = await _get_client(agency["org_id"], client_id)
    if not client:
        return {"error": "Client not found."}
    goal = body.goal or f"Full package trip to {body.destination} for {client['name']}"
    job_body = PlanJobRequest(goal=goal, origin=body.origin or None, destination=body.destination, scope="full_trip")
    job = jobs.launch(
        "plan",
        lambda: _run_plan_job(job_body, None),
        meta={"scope": "full_trip", "goal": goal, "client_id": client_id},
        user_id=None,
    )
    return {"job": jobs.public(job), "client": {"id": client_id, "name": client["name"]}}


@router.post("/deliver")
async def deliver(body: DeliverRequest, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    """Compile a completed plan into a PDF + interactive link and send to the client."""
    from app.shared import create_shared
    from app.tools import telegram, trip_pdf

    client = await _get_client(agency["org_id"], body.client_id)
    if not client:
        return {"error": "Client not found."}
    job = await jobs.get(body.job_id)
    results = ((job or {}).get("result") or {}).get("results") or {}
    if not results:
        return {"error": "That plan isn't ready yet."}

    dest = ((results.get("chief") or {}).get("data") or {}).get("destination") or "Trip"
    title = f"{dest} — {client['name']}"

    token = await create_shared(snapshot=results, title=title, org_id=agency["org_id"])
    share_url = f"{settings.public_base_url.rstrip('/')}/s/{token}"

    pdf = trip_pdf.build_trip_pdf(results, title=title, agency=agency.get("org_name") or "Journava")
    filename = f"{dest.replace(' ', '_')}_itinerary.pdf"

    delivered, detail = False, "No Telegram chat id on file for this client."
    if client.get("telegram_chat_id"):
        caption = f"<b>{title}</b>\nYour full itinerary is attached. View it interactively: {share_url}"
        delivered, detail = await telegram.deliver_document(
            client["telegram_chat_id"], pdf, filename, caption
        )
    return {
        "share_url": share_url,
        "token": token,
        "pdf_bytes": len(pdf),
        "delivered": delivered,
        "detail": detail,
    }
