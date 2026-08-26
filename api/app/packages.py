"""Public Package Builder — an agency's branded, no-account lead funnel.

The agency publishes a page (a token'd URL). A prospective client opens it with
no account, describes the trip they want, and the full 21-agent mesh auto-drafts
a complete package. The client watches it build and can open the finished plan;
the agency gets a warm lead with the AI-drafted package already attached to it.

Two surfaces:
- `config_router` (/agency/package-page, authed) — the owner enables + brands it.
- `public_router` (/packages/*, no auth — allowlisted in AuthMiddleware) — the
  client-facing page, submission, and live build status.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth.deps import require_agency
from app.core import db
from app.core.settings import settings
from app.runtime import jobs
from app.runtime.router import PlanJobRequest, _run_plan_job

logger = logging.getLogger("journava")

config_router = APIRouter(prefix=f"{settings.api_prefix}/agency", tags=["agency"])
public_router = APIRouter(prefix=f"{settings.api_prefix}/packages", tags=["packages"])


# --------------------------------------------------------------------------- #
# Console side — the owner enables + brands the page
# --------------------------------------------------------------------------- #


class PagackeConfig(BaseModel):
    headline: str | None = None
    subhead: str | None = None
    enabled: bool = True


async def _get_or_create_page(org_id: str, org_name: str | None) -> dict[str, Any]:
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM package_pages WHERE org_id = $1", org_id)
        if row is None:
            token = secrets.token_urlsafe(7)
            row = await conn.fetchrow(
                """INSERT INTO package_pages (org_id, token, org_name, headline, subhead, enabled)
                   VALUES ($1,$2,$3,$4,$5,TRUE) RETURNING *""",
                org_id,
                token,
                org_name,
                f"Plan your trip with {org_name or 'us'}",
                "Tell us what you dream of and our AI travel designer drafts your full package in minutes.",
            )
    return dict(row)


def _page_public(row: dict[str, Any]) -> dict[str, Any]:
    base = (settings.public_base_url or "").rstrip("/")
    return {
        "token": row["token"],
        "org_name": row.get("org_name"),
        "headline": row.get("headline"),
        "subhead": row.get("subhead"),
        "enabled": row.get("enabled", True),
        "url": f"{base}/p/{row['token']}" if base else f"/p/{row['token']}",
    }


@config_router.get("/package-page")
async def get_page(agency: dict = Depends(require_agency)) -> dict[str, Any]:
    row = await _get_or_create_page(agency["org_id"], agency.get("org_name"))
    return {"page": _page_public(row)}


@config_router.post("/package-page")
async def update_page(body: PagackeConfig, agency: dict = Depends(require_agency)) -> dict[str, Any]:
    await _get_or_create_page(agency["org_id"], agency.get("org_name"))
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE package_pages
               SET headline = COALESCE($2, headline),
                   subhead = COALESCE($3, subhead),
                   enabled = $4
               WHERE org_id = $1 RETURNING *""",
            agency["org_id"],
            body.headline,
            body.subhead,
            body.enabled,
        )
    return {"page": _page_public(dict(row))}


# --------------------------------------------------------------------------- #
# Public side — the client-facing page + submission + live status
# --------------------------------------------------------------------------- #


class PackageRequestIn(BaseModel):
    name: str
    contact: str | None = None  # email or WhatsApp — how the agency reaches them
    destination: str
    goal: str | None = None
    budget: str | None = None
    dates: str | None = None
    travellers: int = 2


async def _page_by_token(token: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM package_pages WHERE token = $1", token)
    return dict(row) if row else None


@public_router.get("/{token}")
async def public_page(token: str) -> dict[str, Any]:
    """The branded page a prospective client sees (no account)."""
    page = await _page_by_token(token)
    if not page or not page.get("enabled"):
        return {"found": False}
    return {
        "found": True,
        "org_name": page.get("org_name") or "Your travel agency",
        "headline": page.get("headline"),
        "subhead": page.get("subhead"),
    }


@public_router.post("/{token}/request")
async def submit_request(token: str, body: PackageRequestIn, request: Request) -> dict[str, Any]:
    """A client submits their wishes → capture the lead + launch the auto-plan."""
    page = await _page_by_token(token)
    if not page or not page.get("enabled"):
        raise HTTPException(status_code=404, detail="This planning page is not available.")
    org_id = page["org_id"]

    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    goal = body.goal or (
        f"Full package trip to {body.destination} for {body.travellers} "
        f"traveller(s){f', budget {body.budget}' if body.budget else ''}"
        f"{f', dates {body.dates}' if body.dates else ''}."
    )
    job_body = PlanJobRequest(goal=goal, destination=body.destination, scope="full_trip")
    job = jobs.launch(
        "plan",
        lambda: _run_plan_job(job_body, None),
        meta={"scope": "full_trip", "goal": goal, "package_page": token},
        user_id=None,
    )
    job_id = jobs.public(job)["id"]

    # Capture the lead against the agency, with the auto-plan job attached.
    is_whatsapp = bool(body.contact and not ("@" in body.contact))
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO agency_clients
                       (org_id, name, email, whatsapp, channel, source, destination, job_id, notes)
                   VALUES ($1,$2,$3,$4,$5,'package_page',$6,$7,$8)""",
                uuid.UUID(org_id),
                body.name,
                None if is_whatsapp else body.contact,
                body.contact if is_whatsapp else None,
                "whatsapp" if is_whatsapp else "telegram",
                body.destination,
                job_id,
                goal,
            )
    except Exception as exc:  # noqa: BLE001 — never fail the client on a lead write
        logger.warning("package lead capture failed: %s", exc)

    return {"job_id": job_id, "org_name": page.get("org_name")}


@public_router.get("/job/{job_id}")
async def public_job_status(job_id: str) -> dict[str, Any]:
    """Poll the auto-plan; when done, publish a shareable link the client opens."""
    from app.shared import create_shared

    job = await jobs.get(job_id)
    if not job:
        return {"status": "unknown"}
    status = job.get("status", "running")
    out: dict[str, Any] = {"status": status}
    if status == "done":
        results = (job.get("result") or {}).get("results") or {}
        dest = ((results.get("chief") or {}).get("data") or {}).get("destination") or "Your trip"
        out["destination"] = dest
        if results:
            token = await create_shared(snapshot=results, title=str(dest))
            out["share_token"] = token
            # Attach the finished package's link to the lead so the agency sees it.
            pool = await db.get_pool()
            if pool is not None:
                try:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE agency_clients SET share_token = $2 WHERE job_id = $1",
                            job_id,
                            token,
                        )
                except Exception:  # noqa: BLE001
                    pass
    elif status == "error":
        out["error"] = job.get("error")
    return out
