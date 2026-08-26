"""Journava FastAPI application — hosts the orchestrator and all agents (spec §5)."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents import REGISTRY, goal_parser
from app.agents.memory import MemoryAgent
from app.agents.schemas import TravelerProfile, TripRequest
from app.auth import store as auth_store
from app.auth.deps import current_user_id
from app.auth.middleware import AuthMiddleware
from app.auth.router import router as auth_router
from app.agency import router as agency_router
from app.assistant import router as assistant_router
from app.bookings import router as bookings_router
from app.demo import router as demo_router
from app.escrow import router as escrow_router
from app.finance import router as finance_router
from app.firewall import router as firewall_router
from app.guardian import router as guardian_router
from app.negotiation import router as negotiation_router
from app.itinerary import router as itinerary_router
from app.monitor import router as monitor_router
from app.policy import router as policy_router
from app.runtime.router import router as runtime_router
from app.agent_studio import router as studio_router
from app.kb import router as kb_router
from app.packages import config_router as package_config_router
from app.packages import public_router as package_public_router
from app.inbox import config_router as inbox_config_router
from app.inbox import webhook_router as inbox_webhook_router
from app.hotels import config_router as hotel_config_router
from app.hotels import public_router as hotel_public_router
from app.collab import router as collab_router
from app.compare import router as compare_router
from app.saved import router as saved_router
from app.intel import router as intel_router
from app.content import router as content_router
from app.chaos_lab import router as chaos_router
from app.mapping import geo_router
from app.mapping import router as mapping_router
from app.pricewatch import router as pricewatch_router
from app.expenses import router as expenses_router
from app.shared import router as shared_router
from app.supplier.ai import router as supplier_ai_router
from app.supplier.router import router as supplier_router
from app.brain import bookings, gnosion_client, history, outcomes, trip_store
from app.brain.trip_store import reconstruct_request
from app.core import (
    cache,
    db,
    llm_discovery,
    llm_presets,
    llm_providers,
    sse,
    vault,
    vault_probes,
)
from app.core.settings import settings
from app.graph import auto_rebook, booking_flow, scopes
from app.graph.disruption import handle_disruption
from app.graph.supervisor import cancel_run as _cancel_plan_run
from app.graph.supervisor import run_plan
from app.tools import camofox as camofox_tool

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("journava")


async def _reminder_loop() -> None:
    """Every ~6h, ping managers about upcoming check-ins and travellers about
    imminent trips (best-effort). Both sweeps dedupe on their own marker column,
    so a ping fires once per booking/trip regardless of how often the loop runs."""
    import asyncio

    from app.bookings import send_daily_digests, send_due_reminders, send_trip_countdowns
    from app.pricewatch import run_price_watches

    while True:
        try:
            await asyncio.sleep(6 * 3600)
            await send_due_reminders()
            await send_trip_countdowns()
            await send_daily_digests()  # "what to do today" for trips in progress
            await run_price_watches()  # re-price armed fare watches; alert on drops
        except asyncio.CancelledError:  # noqa: PERF203
            break
        except Exception as exc:  # noqa: BLE001
            logger.info("reminder loop error: %s", exc)


def _is_demo_trip(trip: dict[str, object] | None) -> bool:
    """A seeded demo trip must never masquerade as the traveller's own trip.

    Matches the current marker plus the legacy Venice-demo fingerprint, so a
    trip auto-seeded by an older build (and stuck in durable storage) is
    recognised and cleared without any manual DB surgery on prod.
    """
    if not trip:
        return False
    if trip.get("_demo"):
        return True
    chief = trip.get("chief") or {}
    data = (chief.get("data") if isinstance(chief, dict) else {}) or {}
    summary = str(chief.get("summary") or "") if isinstance(chief, dict) else ""
    return (
        data.get("destination") == "Venice, Italy"
        and data.get("origin") == "Kuala Lumpur (KUL)"
        and summary.startswith("7-day Venice trip for 2")
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Warm the optional dependencies; none of them are required to boot."""
    import asyncio

    logger.info("Journava API starting (%s)", settings.environment)
    await db.init_schema()
    await auth_store.seed_demo_users()
    await cache.get_redis()
    reminder_task = asyncio.create_task(_reminder_loop())
    # Restore the last trip from durable storage. My Trip must stay EMPTY until
    # the traveller plans one and taps "Add to my trip" — never show a trip they
    # didn't create (the old Venice demo-trip seed confused real users). Any demo
    # trip that leaked into durable storage from an older build is cleared here,
    # so prod self-heals on the next deploy.
    restored = await trip_store.load_trip_durable()
    if _is_demo_trip(restored):
        await trip_store.delete_active()
        logger.info("Cleared a stale demo trip from durable storage")
    elif restored is not None:
        logger.info("Active trip restored from durable storage")
    yield
    reminder_task.cancel()
    await cache.close_redis()
    await db.close_pool()
    logger.info("Journava API stopped")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Autonomous multi-agent travel intelligence.",
    lifespan=lifespan,
)

# Auth gate is added BEFORE CORS so CORS ends up outermost — a 401/403 from the
# auth middleware still carries the CORS headers the browser needs to read it.
app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(runtime_router)
app.include_router(supplier_router)
app.include_router(supplier_ai_router)
app.include_router(assistant_router)
app.include_router(agency_router)
app.include_router(policy_router)
app.include_router(monitor_router)
app.include_router(escrow_router)
app.include_router(itinerary_router)
app.include_router(firewall_router)
app.include_router(shared_router)
app.include_router(bookings_router)
app.include_router(finance_router)
app.include_router(negotiation_router)
app.include_router(guardian_router)
app.include_router(demo_router)
app.include_router(saved_router)
app.include_router(collab_router)
app.include_router(compare_router)
app.include_router(studio_router)
app.include_router(kb_router)
app.include_router(package_config_router)
app.include_router(package_public_router)
app.include_router(inbox_config_router)
app.include_router(inbox_webhook_router)
app.include_router(hotel_config_router)
app.include_router(hotel_public_router)
app.include_router(intel_router)
app.include_router(content_router)
app.include_router(chaos_router)
app.include_router(mapping_router)
app.include_router(geo_router)
app.include_router(pricewatch_router)
app.include_router(expenses_router)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #


@app.get("/health", tags=["ops"])
async def health() -> dict[str, object]:
    """Liveness + dependency report. Always 200 so the container stays up."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "agents": len(REGISTRY),
        "dependencies": {
            "postgres": await db.healthy(),
            "redis": await cache.get_redis() is not None,
            # False here means the in-process fallback is serving memory. The
            # app still works; it just isn't the real brain, and saying so beats
            # a green tick that hides it.
            "gnosion": gnosion_client.available(),
            "camofox": await camofox_tool.available(),
        },
        "memory_backend": gnosion_client.snapshot()["backend"],
        "sse_subscribers": sse.subscriber_count(),
    }


# --------------------------------------------------------------------------- #
# Agent stream (SSE)
# --------------------------------------------------------------------------- #


@app.get(f"{settings.api_prefix}/events", tags=["agents"])
async def agent_events() -> StreamingResponse:
    """Live agent event stream consumed by the Agent Control Center (§3.4)."""

    async def event_source() -> AsyncIterator[str]:
        async for payload in sse.subscribe():
            if payload == "__heartbeat__":
                yield ": keep-alive\n\n"
            else:
                yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # never buffer SSE at the proxy
        },
    )


@app.get(f"{settings.api_prefix}/agents", tags=["agents"])
async def list_agents() -> list[dict[str, str]]:
    """The agent roster shown in the control center."""
    return [
        {"slug": agent.slug, "name": agent.name, "role": agent.role} for agent in REGISTRY.values()
    ]


# --------------------------------------------------------------------------- #
# Planning & profile
# --------------------------------------------------------------------------- #


class PlanRequest(TripRequest):
    """A trip request plus the scope that decides which agents run.

    Scoping is what keeps an answer proportionate to the question: a
    flights-only ask should not wake the visa, shopping and language agents.
    """

    scope: str = scopes.DEFAULT_SCOPE


class PlanResponse(BaseModel):
    results: dict[str, object]
    scope: str
    history_id: str | None = None
    duration_ms: int


@app.post(f"{settings.api_prefix}/plan", response_model=PlanResponse, tags=["planning"])
async def plan(body: PlanRequest, request: Request) -> PlanResponse:
    """Run a planning pass for one scope.

    The signed-in user's profile is read first: a preference narrows scope, its
    absence means global search (§7.5). The result is persisted as the active
    trip, and recorded in history so it can be reopened without replaying agents.
    """
    import time

    scope = scopes.get(body.scope)
    trip_request = TripRequest.model_validate(
        body.model_dump(exclude={"scope"}, exclude_none=True)
    )
    profile = MemoryAgent.load_profile(current_user_id(request))

    started = time.monotonic()
    results = await run_plan(trip_request, profile, scope=scope)
    duration_ms = int((time.monotonic() - started) * 1000)

    from app.brain import knowledge

    try:
        await knowledge.record_from_plan(results)
    except Exception:  # noqa: BLE001 — knowledge capture must never fail a plan
        logger.warning("record_from_plan failed", exc_info=True)

    # A plan is NOT auto-saved as the active trip — that only happens when the
    # traveller explicitly taps "Add to my trip" (POST /trip/save).

    entry = await history.record(
        scope=scope.slug,
        goal=trip_request.goal,
        results=results,
        duration_ms=duration_ms,
    )
    return PlanResponse(
        results=results,
        scope=scope.slug,
        history_id=entry.get("id"),
        duration_ms=duration_ms,
    )


@app.post(f"{settings.api_prefix}/cancel", tags=["planning"])
async def cancel_plan() -> dict[str, bool]:
    """Request cancellation of the currently running plan.

    The supervisor checks the cancel flag between tiers; in-flight agents
    will finish but no further tiers will start.
    """
    _cancel_plan_run()
    sse.publish("system", "idle", "Cancellation requested…")
    return {"cancelled": True}


# --------------------------------------------------------------------------- #
# Active trip
# --------------------------------------------------------------------------- #


@app.get(f"{settings.api_prefix}/rates", tags=["misc"])
async def fx_rates(base: str = "MYR") -> dict[str, object]:
    """FX rates keyed by currency, expressed as units-per-1-`base` (Frankfurter).

    Drives the result-page currency switcher: to show a price of `amount` in
    currency C using display base B, the frontend divides by `rates[C]`.
    """
    from app.tools import frankfurter

    base = (base or "MYR").upper()
    rates = await frankfurter.rates(base) or {}
    return {"base": base, "rates": {base: 1.0, **rates}}


@app.get(f"{settings.api_prefix}/trip", tags=["trip"])
async def get_trip() -> dict[str, object]:
    """Return the latest active trip (most recent plan result)."""
    trip = await trip_store.load_trip_durable()
    # A seeded demo trip is never the traveller's own — keep My Trip empty until
    # they confirm a real plan. (Filtered, not deleted: the agency demo reads the
    # same store for its escrow/guardian panels.)
    if trip is None or _is_demo_trip(trip):
        return {"trip": None}
    return {"trip": trip}


@app.get(f"{settings.api_prefix}/trip/ready", tags=["trip"])
async def trip_ready() -> dict[str, object]:
    """The most recent completed full-trip plan (from history) — so the home can
    show a 'your plan is ready to view' banner after a background run finishes and
    pings the traveller. Returns {ready: null} when there's nothing recent."""
    from app.brain import history

    try:
        entries = await history.list_entries(limit=10)
    except Exception:  # noqa: BLE001 — never break the home
        return {"ready": None}
    for e in entries:
        if (e.get("scope") or "") == "full_trip" and (e.get("destination") or e.get("goal")):
            return {
                "ready": {
                    "id": e.get("id"),
                    "destination": e.get("destination"),
                    "goal": e.get("goal"),
                }
            }
    return {"ready": None}


class TripSave(BaseModel):
    results: dict[str, object]


@app.post(f"{settings.api_prefix}/trip/save", tags=["trip"])
async def save_active_trip(request: TripSave) -> dict[str, object]:
    """Adopt a plan as the active trip — the 'Add to my trip' action."""
    trip_id = await trip_store.save_trip_durable(request.results)
    return {"ok": True, "trip_id": trip_id}


@app.delete(f"{settings.api_prefix}/trip", tags=["trip"])
async def delete_active_trip() -> dict[str, object]:
    """Remove the active trip (My Trip goes back to empty)."""
    await trip_store.delete_active()
    return {"deleted": True}


@app.get(f"{settings.api_prefix}/trip/thumbnail", tags=["trip"])
async def trip_thumbnail(destination: str = "") -> dict[str, object]:
    """A compressed data-URI photo for a destination (trip-card thumbnail)."""
    from app.tools import destination_image

    return {"destination": destination, "thumbnail": await destination_image.thumbnail(destination)}


class ItineraryUpdate(BaseModel):
    items: list[dict[str, object]]


@app.post(f"{settings.api_prefix}/trip/itinerary", tags=["trip"])
async def save_itinerary(request: ItineraryUpdate) -> dict[str, object]:
    """Persist a reordered / edited itinerary for the active trip."""
    updated = await trip_store.update_itinerary(list(request.items))
    if updated is None:
        raise HTTPException(status_code=404, detail="No active trip to edit")
    return {"trip": updated}


class ItineraryRefine(BaseModel):
    instruction: str | None = None


@app.post(f"{settings.api_prefix}/trip/itinerary/refine", tags=["trip"])
async def refine_itinerary(request: ItineraryRefine) -> dict[str, object]:
    """Ask the agents to add activities and realign the schedule."""
    updated = await trip_store.refine_itinerary(request.instruction)
    if updated is None:
        raise HTTPException(status_code=404, detail="No active trip to refine")
    return {"trip": updated}


class ItineraryBuild(BaseModel):
    days: int = 3
    picks: list[dict[str, object]] = []
    arrival: str | None = None


@app.post(f"{settings.api_prefix}/trip/itinerary/build", tags=["trip"])
async def build_itinerary(request: ItineraryBuild) -> dict[str, object]:
    """Schedule the traveller's PICKED places into a full N-day itinerary; the
    unpicked suggestions come back as `itinerary.backup`."""
    updated = await trip_store.build_itinerary(
        list(request.picks), max(1, request.days), arrival=request.arrival
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="No active trip to build")
    return {"trip": updated}


class TripShare(BaseModel):
    results: dict[str, object] | None = None


@app.post(f"{settings.api_prefix}/trip/share", tags=["trip"])
async def share_trip(request: TripShare) -> dict[str, object]:
    """Create a public, read-only share link for the trip — friends open the
    interactive plan with no account (reuses the shared-plan view + story)."""
    from app.shared import create_shared

    snap = request.results or (await trip_store.load_trip_durable() or {})
    if not snap:
        raise HTTPException(status_code=404, detail="No trip to share yet.")
    dest = ((snap.get("chief") or {}).get("data") or {}).get("destination") or "Your trip"
    token = await create_shared(snapshot=snap, title=str(dest))
    base = (settings.public_base_url or "").rstrip("/")
    return {"token": token, "url": f"{base}/s/{token}" if base else f"/s/{token}"}


class BudgetOptimize(BaseModel):
    budget_amount: float
    currency: str | None = None


@app.post(f"{settings.api_prefix}/trip/optimize", tags=["trip"])
async def optimize_trip(request: BudgetOptimize) -> dict[str, object]:
    """Fit the active trip to a budget — an agent prices it and trims the
    priciest activities to backup until it fits, reversibly."""
    updated = await trip_store.optimize_to_budget(request.budget_amount, request.currency)
    if updated is None:
        raise HTTPException(status_code=404, detail="No active trip to optimize")
    return updated


class ItineraryPick(BaseModel):
    title: str
    action: Literal["add", "remove"]


@app.post(f"{settings.api_prefix}/trip/itinerary/pick", tags=["trip"])
async def pick_itinerary(request: ItineraryPick) -> dict[str, object]:
    """Instantly move a place between the schedule and the backup list — "add"
    pulls a backup idea into the plan, "remove" drops a scheduled place back to
    backup. No LLM, so the picker feels immediate."""
    updated = await trip_store.move_place(request.title, request.action)
    if updated is None:
        raise HTTPException(status_code=404, detail="No active trip")
    return {"trip": updated}


class ReplanFlights(BaseModel):
    saved_id: str
    simulate: str | None = None  # delayed | cancelled


@app.post(f"{settings.api_prefix}/trip/replan-flights", tags=["trip"])
async def replan_flights(request: ReplanFlights) -> dict[str, object]:
    """Card-level re-plan: mark the picked/cheapest flight disrupted and surface
    the plan's OTHER flights as alternatives, flagged within budget — instant,
    from the saved snapshot (no re-crawl)."""
    import json as _json
    import uuid as _uuid

    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT snapshot FROM saved_results WHERE id = $1", _uuid.UUID(request.saved_id))
    if not row:
        raise HTTPException(status_code=404, detail="Trip not found")
    snap = row["snapshot"]
    snap = _json.loads(snap) if isinstance(snap, str) else snap

    flight = (snap or {}).get("flight") or {}
    opts = flight.get("options") or []
    route = (flight.get("data") or {}).get("route") or {}
    resolved = ((snap or {}).get("chief") or {}).get("data", {}).get("resolved_request") or {}
    budget_amt = resolved.get("budget_amount")
    currency = resolved.get("budget_currency") or next(
        (o.get("price_currency") for o in opts if o.get("price_currency")), "MYR"
    )
    priced = sorted((o for o in opts if o.get("price_amount") is not None), key=lambda o: float(o["price_amount"]))
    status = request.simulate if request.simulate in ("delayed", "cancelled") else "delayed"
    disrupted = priced[0] if priced else (opts[0] if opts else None)

    def _within(o: dict) -> bool | None:
        p = o.get("price_amount")
        if budget_amt and p is not None:
            return float(p) <= float(budget_amt)
        return None

    alts = [o for o in (priced or opts) if o is not disrupted][:6]
    return {
        "status": status,
        "route": f"{route.get('origin', '')}→{route.get('destination', '')}",
        "disrupted": {
            "title": (disrupted or {}).get("title"),
            "price_amount": (disrupted or {}).get("price_amount"),
            "price_currency": (disrupted or {}).get("price_currency") or currency,
        },
        "alternatives": [
            {"id": o.get("id"), "title": o.get("title"), "price_amount": o.get("price_amount"),
             "price_currency": o.get("price_currency") or currency, "bookable": o.get("bookable", False),
             "within_budget": _within(o)}
            for o in alts
        ],
        "budget": {
            "amount": float(budget_amt) if budget_amt else None, "currency": currency,
            "within_budget_count": sum(1 for o in alts if _within(o) is True), "total": len(alts),
        },
    }


@app.post(f"{settings.api_prefix}/trip/local-intel", tags=["trip"])
async def trip_local_intel() -> dict[str, object]:
    """Crowd levels + best-times per place + social do's/don'ts for the trip."""
    from app.tools import local_intel

    results = await trip_store.load_trip_durable() or {}
    if not results:
        raise HTTPException(status_code=404, detail="No active trip")
    chief = (results.get("chief") or {}).get("data") or {}
    destination = chief.get("destination") or (chief.get("resolved_request") or {}).get("destination") or ""
    seen: set[str] = set()
    places: list[dict[str, object]] = []
    for opt in (results.get("research") or {}).get("options", []) or []:
        if opt.get("kind") in ("activity", "restaurant") and opt.get("title") and opt["title"] not in seen:
            seen.add(opt["title"])
            places.append({"name": opt["title"], "kind": opt["kind"]})
    for item in (results.get("itinerary") or {}).get("items", []) or []:
        if item.get("title") and item["title"] not in seen and item.get("kind") in ("activity", "meal"):
            seen.add(item["title"])
            places.append({"name": item["title"], "kind": item.get("kind")})
    return await local_intel.gather(destination, places[:12])


# --------------------------------------------------------------------------- #
# Knowledge library — findings the agents documented, grouped by category
# --------------------------------------------------------------------------- #


@app.get(f"{settings.api_prefix}/knowledge", tags=["knowledge"])
async def knowledge_library(category: str | None = None, destination: str | None = None) -> dict[str, object]:
    """Documented travel findings. Grouped by category unless filtered."""
    from app.brain import knowledge

    if category or destination:
        return {"notes": await knowledge.list_notes(category, destination)}
    return {"grouped": await knowledge.grouped(), "categories": list(knowledge.CATEGORIES)}


# --------------------------------------------------------------------------- #
# Outcome learning (§7 ③) — the flywheel the Research Board's feedback drives
# --------------------------------------------------------------------------- #


class OutcomeRequest(BaseModel):
    domain: str
    recommendation: dict[str, object] = {}
    accepted: bool
    agent: str = "memory"
    trip_id: str | None = None
    user_note: str | None = None


@app.post(f"{settings.api_prefix}/outcome", tags=["brain"])
async def record_outcome(request: OutcomeRequest) -> dict[str, object]:
    """Record an accepted/rejected recommendation so the next plan is smarter."""
    return await outcomes.record(
        request.domain,
        dict(request.recommendation),
        request.accepted,
        agent=request.agent,
        trip_id=request.trip_id,
        user_note=request.user_note,
    )


@app.get(f"{settings.api_prefix}/outcome/stats", tags=["brain"])
async def outcome_stats() -> list[dict[str, object]]:
    """Accepted/rejected tallies per domain."""
    return await outcomes.stats()


# --------------------------------------------------------------------------- #
# Disruption simulation (§3 "wow flow")
# --------------------------------------------------------------------------- #


class DisruptionRequest(BaseModel):
    trip_id: str | None = None
    disruption_type: Literal["flight_cancelled", "weather_alert", "budget_exceeded"] = (
        "flight_cancelled"
    )
    affected_agent: str = "flight"


class DisruptionResponse(BaseModel):
    recovery_plan: dict[str, object]
    additional_cost: str
    #: Before/after prices and whether the two were actually comparable.
    cost_detail: dict[str, object]
    agents_activated: list[str]
    summary: str
    disruption_type: str


@app.post(
    f"{settings.api_prefix}/disruption", response_model=DisruptionResponse, tags=["disruption"]
)
async def disruption(request: DisruptionRequest) -> DisruptionResponse:
    """Simulate a disruption and run the autonomous recovery cascade.

    This is the demo "money shot": agents rebuild the trip live.
    """
    # Load the active trip as the baseline
    original_results = await trip_store.load_trip_durable() or {}
    profile = MemoryAgent.load_profile()

    # Rebuild the trip request from what the Chief resolved. `resolved_request`
    # is the canonical mirror the Chief writes for exactly this purpose — reading
    # `data["destination"]` directly would miss it, and the recovery would then
    # replan for "unknown".
    original_request = reconstruct_request(
        original_results, goal=f"Recovery from {request.disruption_type}"
    )

    recovery = await handle_disruption(
        disruption_type=request.disruption_type,
        affected_agent=request.affected_agent,
        original_request=original_request,
        profile=profile,
        original_results=original_results,
    )

    # Update the active trip with the recovery plan
    updated_results = {**original_results, **recovery.get("recovery_plan", {})}
    await trip_store.save_trip_durable(updated_results)

    return DisruptionResponse(
        recovery_plan=recovery["recovery_plan"],
        additional_cost=recovery["additional_cost"],
        cost_detail=recovery["cost_detail"],
        agents_activated=recovery["agents_activated"],
        summary=recovery["summary"],
        disruption_type=recovery["disruption_type"],
    )


@app.get(f"{settings.api_prefix}/profile", response_model=TravelerProfile, tags=["profile"])
async def get_profile(request: Request) -> TravelerProfile:
    return MemoryAgent.load_profile(current_user_id(request))


@app.post(f"{settings.api_prefix}/profile", response_model=TravelerProfile, tags=["profile"])
async def save_profile(profile: TravelerProfile, request: Request) -> TravelerProfile:
    """Persist the signed-in user's standing preferences (§3.5)."""
    MemoryAgent.save_profile(profile, current_user_id(request))
    sse.publish("memory", "active", "Traveler profile updated")
    return profile


# --------------------------------------------------------------------------- #
# Engine — AI model providers (rotation pool)
# --------------------------------------------------------------------------- #


class ProviderCreate(BaseModel):
    name: str
    litellm_model: str
    api_key: str
    priority: int = 0
    enabled: bool = True
    max_rpm: int | None = None
    max_rpd: int | None = None
    max_tpd: int | None = None
    #: Refuse to save unless the key passes its probe. The UI defaults this on.
    require_test: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = None
    litellm_model: str | None = None
    api_key: str | None = None
    priority: int | None = None
    enabled: bool | None = None
    max_rpm: int | None = None
    max_rpd: int | None = None
    max_tpd: int | None = None


class ProviderReorder(BaseModel):
    ordered_ids: list[str]


class ProviderTestRequest(BaseModel):
    """Test an arbitrary model+key pair *before* it is stored."""

    litellm_model: str
    api_key: str


@app.get(f"{settings.api_prefix}/engine/providers", tags=["engine"])
async def engine_list_providers() -> list[dict[str, object]]:
    """The rotation pool: health, quota usage, priority. Keys always masked."""
    return await llm_providers.list_providers()


@app.get(f"{settings.api_prefix}/engine/catalogue", tags=["engine"])
async def engine_catalogue() -> dict[str, object]:
    """Known model presets plus the local fallback state, for the add form."""
    return {
        "presets": llm_presets.PRESETS,
        "ollama_fallback": {
            "enabled": settings.ollama_fallback_enabled,
            "model": settings.ollama_fallback_model,
            "note": (
                "Tried only after every cloud provider fails. Needs no key, but "
                "Ollama must be running locally."
            ),
        },
    }


class ModelDiscoveryRequest(BaseModel):
    provider: str
    api_key: str | None = None


@app.post(f"{settings.api_prefix}/engine/models", tags=["engine"])
async def engine_discover_models(request: ModelDiscoveryRequest) -> dict[str, object]:
    """Ask a provider which models it will serve right now.

    The preset list is a convenience and it goes stale — Groq retired its Llama
    models while our presets still offered them, which produces a `model_not_found`
    that looks like a bad key. This endpoint is the source of truth.
    """
    try:
        models = await llm_discovery.list_models(request.provider, request.api_key)
    except llm_discovery.DiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"provider": request.provider, "count": len(models), "models": models}


@app.post(f"{settings.api_prefix}/engine/test", tags=["engine"])
async def engine_test_candidate(request: ProviderTestRequest) -> dict[str, object]:
    """Ping a model+key pair without saving it.

    This is the check that makes the add form trustworthy: the operator learns
    whether a key works while they are still looking at the form, rather than
    discovering it when an agent run fails.
    """
    return await vault_probes.probe_model(request.litellm_model, request.api_key)


@app.post(f"{settings.api_prefix}/engine/providers", tags=["engine"])
async def engine_create_provider(provider: ProviderCreate) -> dict[str, object]:
    """Add a provider to the rotation pool, testing the key first."""
    verdict = await vault_probes.probe_model(provider.litellm_model, provider.api_key)
    if provider.require_test and not verdict["ok"]:
        raise HTTPException(
            status_code=400,
            detail=f"Key test failed ({verdict['status']}): {verdict['message']}",
        )

    try:
        result = await llm_providers.create_provider(
            name=provider.name,
            litellm_model=provider.litellm_model,
            api_key=provider.api_key,
            priority=provider.priority,
            enabled=provider.enabled,
            max_rpm=provider.max_rpm,
            max_rpd=provider.max_rpd,
            max_tpd=provider.max_tpd,
            status=verdict["status"],
            status_detail=verdict["message"],
        )
    except llm_providers.ProviderStoreError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Provider could not be saved: {exc}",
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="Provider could not be saved — the database is unavailable.",
        )
    return {**result, "test": verdict}


@app.patch(f"{settings.api_prefix}/engine/providers/{{provider_id}}", tags=["engine"])
async def engine_update_provider(provider_id: str, update: ProviderUpdate) -> dict[str, object]:
    """Update a provider. A rotated key is re-tested before it is trusted."""
    verdict: dict[str, object] | None = None
    if update.api_key:
        model = update.litellm_model
        if not model:
            existing = await llm_providers.get_provider_full(provider_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="Provider not found")
            model = existing["litellm_model"]
        verdict = await vault_probes.probe_model(model, update.api_key)

    result = await llm_providers.update_provider(
        provider_id,
        **update.model_dump(exclude_none=True),
        **({"status": verdict["status"], "status_detail": verdict["message"]} if verdict else {}),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {**result, "test": verdict} if verdict else result


@app.post(f"{settings.api_prefix}/engine/providers/reorder", tags=["engine"])
async def engine_reorder_providers(request: ProviderReorder) -> dict[str, object]:
    """Apply a drag-and-drop rotation order."""
    if not await llm_providers.reorder_providers(request.ordered_ids):
        raise HTTPException(status_code=503, detail="Could not reorder providers")
    return {"reordered": True, "providers": await llm_providers.list_providers()}


@app.post(f"{settings.api_prefix}/engine/providers/{{provider_id}}/reset", tags=["engine"])
async def engine_reset_provider(provider_id: str) -> dict[str, object]:
    """Clear a provider's status, cooldown and metered usage."""
    result = await llm_providers.reset_provider(provider_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return result


@app.delete(f"{settings.api_prefix}/engine/providers/{{provider_id}}", tags=["engine"])
async def engine_delete_provider(provider_id: str) -> dict[str, object]:
    """Remove a provider from the pool."""
    if not await llm_providers.delete_provider(provider_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"deleted": True}


@app.post(f"{settings.api_prefix}/engine/providers/{{provider_id}}/test", tags=["engine"])
async def engine_test_provider(provider_id: str) -> dict[str, object]:
    """Re-test a stored provider and record the verdict."""
    provider = await llm_providers.get_provider_full(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    verdict = await vault_probes.probe_model(provider["litellm_model"], provider["api_key"])
    await llm_providers.mark_status(provider_id, verdict["status"], str(verdict["message"]))
    return {**verdict, "model": provider["litellm_model"]}


@app.get(f"{settings.api_prefix}/engine/stats", tags=["engine"])
async def engine_stats() -> list[dict[str, object]]:
    """Usage stats per model (last 7 days)."""
    return await llm_providers.get_stats()


# --------------------------------------------------------------------------- #
# Brain graph visualization (spec §7 ①)
# --------------------------------------------------------------------------- #


@app.get(f"{settings.api_prefix}/brain/graph", tags=["brain"])
async def brain_graph() -> dict[str, object]:
    """Gnosion knowledge graph as nodes + edges for the Agent Control Center.

    `gnosion_client.graph()` builds this from the live memory counts of every
    declared domain, so the node weights are real and climb as agents learn.
    It reports which backend produced them, and never fabricates a graph.
    """
    return gnosion_client.graph()


@app.get(f"{settings.api_prefix}/brain/snapshot", tags=["brain"])
async def brain_snapshot() -> dict[str, object]:
    """Which memory backend is live, and how much it holds."""
    return gnosion_client.snapshot()


# --------------------------------------------------------------------------- #
# API Vault - every third-party credential, encrypted (spec 9)
# --------------------------------------------------------------------------- #


class CredentialUpsert(BaseModel):
    provider: str
    secret: str | None = None
    extra: dict[str, object] = {}
    label: str | None = None
    enabled: bool = True
    #: Refuse to save a key the probe rejects. Off for providers with no probe.
    require_test: bool = False


class CredentialTest(BaseModel):
    provider: str
    secret: str | None = None
    extra: dict[str, object] = {}


@app.get(f"{settings.api_prefix}/vault/catalogue", tags=["vault"])
async def vault_catalogue() -> dict[str, object]:
    """Every provider Journava can use, and whether it is configured."""
    return {
        "categories": vault.CATEGORIES,
        "providers": await vault.catalogue(),
    }


@app.get(f"{settings.api_prefix}/vault/credentials", tags=["vault"])
async def vault_list(category: str | None = None) -> list[dict[str, object]]:
    """Stored credentials. Secrets are masked and never returned in full."""
    return await vault.list_credentials(category)


@app.post(f"{settings.api_prefix}/vault/test", tags=["vault"])
async def vault_test(request: CredentialTest) -> dict[str, object]:
    """Probe a credential without storing it - the test-before-save path."""
    return await vault_probes.probe(request.provider, request.secret, dict(request.extra))


@app.post(f"{settings.api_prefix}/vault/credentials", tags=["vault"])
async def vault_upsert(request: CredentialUpsert) -> dict[str, object]:
    """Store or rotate a credential, recording its tested health."""
    if request.provider not in vault.PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider {request.provider!r}")

    verdict = await vault_probes.probe(request.provider, request.secret, dict(request.extra))
    if request.require_test and not verdict["ok"]:
        raise HTTPException(
            status_code=400,
            detail=f"Test failed ({verdict['status']}): {verdict['message']}",
        )

    stored = await vault.upsert_credential(
        request.provider,
        secret=request.secret,
        extra=dict(request.extra),
        label=request.label,
        enabled=request.enabled,
        status=verdict["status"],
        status_detail=str(verdict["message"]),
    )
    if stored is None:
        raise HTTPException(
            status_code=503,
            detail="Credential could not be saved - the database is unavailable.",
        )
    vault.invalidate_cache(request.provider)
    return {**stored, "test": verdict}


@app.post(f"{settings.api_prefix}/vault/credentials/{{provider}}/test", tags=["vault"])
async def vault_retest(provider: str) -> dict[str, object]:
    """Re-test a stored credential and record the verdict."""
    resolved = await vault.resolve(provider)
    if resolved is None:
        raise HTTPException(status_code=404, detail="No credential stored")
    verdict = await vault_probes.probe(
        provider, resolved.get("secret"), resolved.get("extra") or {}
    )
    await vault.set_status(provider, verdict["status"], str(verdict["message"]))
    return verdict


@app.delete(f"{settings.api_prefix}/vault/credentials/{{provider}}", tags=["vault"])
async def vault_delete(provider: str) -> dict[str, object]:
    if not await vault.delete_credential(provider):
        raise HTTPException(status_code=404, detail="No credential stored")
    vault.invalidate_cache(provider)
    return {"deleted": True, "provider": provider}


# --------------------------------------------------------------------------- #
# Integrations - notification bots (Telegram, multiple, user-facing)
# --------------------------------------------------------------------------- #


class BotCreate(BaseModel):
    label: str
    bot_token: str
    chat_id: str
    enabled: bool = True


class BotUpdate(BaseModel):
    label: str | None = None
    bot_token: str | None = None  # omit to keep the stored token
    chat_id: str | None = None
    enabled: bool | None = None


_WELCOME = "🎉 <b>Journava connected!</b>\nThis bot will ping you when a background trip plan is ready."
_TEST_MSG = "✅ Journava test message — you're all set."


@app.get(f"{settings.api_prefix}/integrations/bots", tags=["integrations"])
async def bots_list() -> list[dict[str, object]]:
    """Every notification bot (tokens masked)."""
    from app.core import bots

    return await bots.list_bots()


@app.post(f"{settings.api_prefix}/integrations/bots", tags=["integrations"])
async def bots_create(request: BotCreate) -> dict[str, object]:
    """Add a bot, then send it a confirmation message."""
    from app.core import bots
    from app.tools import telegram as telegram_tool

    created = await bots.create_bot(
        request.label.strip() or "Telegram bot",
        request.bot_token.strip(),
        request.chat_id.strip(),
        enabled=request.enabled,
    )
    if created is None:
        raise HTTPException(status_code=503, detail="Could not save the bot.")
    ok, detail = await telegram_tool.send(request.bot_token.strip(), request.chat_id.strip(), _WELCOME)
    return {**created, "test": {"ok": ok, "message": detail}}


@app.patch(f"{settings.api_prefix}/integrations/bots/{{bot_id}}", tags=["integrations"])
async def bots_update(bot_id: str, request: BotUpdate) -> dict[str, object]:
    """Edit a bot or flip its enabled toggle."""
    from app.core import bots

    updated = await bots.update_bot(
        bot_id,
        label=request.label,
        token=request.bot_token,
        chat_id=request.chat_id,
        enabled=request.enabled,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Bot not found")
    return updated


@app.delete(f"{settings.api_prefix}/integrations/bots/{{bot_id}}", tags=["integrations"])
async def bots_delete(bot_id: str) -> dict[str, object]:
    from app.core import bots

    if not await bots.delete_bot(bot_id):
        raise HTTPException(status_code=404, detail="Bot not found")
    return {"deleted": True, "id": bot_id}


@app.post(f"{settings.api_prefix}/integrations/bots/{{bot_id}}/test", tags=["integrations"])
async def bots_test(bot_id: str) -> dict[str, object]:
    from app.core import bots
    from app.tools import telegram as telegram_tool

    creds = await bots.credentials(bot_id)
    if creds is None:
        raise HTTPException(status_code=400, detail="Bot not found or missing credentials.")
    ok, detail = await telegram_tool.send(creds[0], creds[1], _TEST_MSG)
    return {"ok": ok, "message": detail}


# --- Email (Gmail SMTP) channels — same store, platform='email' ------------- #


class EmailChannelIn(BaseModel):
    email: str  # the Gmail address (also the SMTP username)
    app_password: str  # a Google App Password, not the account password
    recipient: str | None = None  # where to send; defaults to the sender
    enabled: bool = True


_EMAIL_TEST_HTML = "✅ <b>Journava email connected.</b><br>You'll now get trip reminders, price-drop alerts and daily plans here."


@app.get(f"{settings.api_prefix}/integrations/email", tags=["integrations"])
async def email_list() -> list[dict[str, object]]:
    """Every connected email channel (app passwords masked)."""
    from app.core import bots

    return [b for b in await bots.list_bots() if b.get("platform") == "email"]


@app.post(f"{settings.api_prefix}/integrations/email", tags=["integrations"])
async def email_create(body: EmailChannelIn) -> dict[str, object]:
    """Connect a Gmail SMTP channel, then send a confirmation email."""
    from app.core import bots
    from app.tools import email as email_tool

    sender = body.email.strip()
    recipient = (body.recipient or sender).strip()
    created = await bots.create_bot(
        sender, body.app_password.strip(), recipient, platform="email", enabled=body.enabled,
    )
    if created is None:
        raise HTTPException(status_code=503, detail="Could not save the email channel.")
    ok, detail = await email_tool.send_one(
        sender, body.app_password.strip(), recipient, "Journava email connected", _EMAIL_TEST_HTML,
    )
    return {**created, "test": {"ok": ok, "message": detail}}


@app.post(f"{settings.api_prefix}/integrations/email/{{channel_id}}/test", tags=["integrations"])
async def email_test(channel_id: str) -> dict[str, object]:
    """Send a test email through a saved channel."""
    from app.core import bots
    from app.tools import email as email_tool

    creds = await bots.email_credentials(channel_id)  # (sender, app_password, recipient)
    if creds is None:
        raise HTTPException(status_code=400, detail="Channel not found or missing credentials.")
    sender, password, recipient = creds
    ok, detail = await email_tool.send_one(sender, password, recipient, "Journava test", _EMAIL_TEST_HTML)
    return {"ok": ok, "message": detail}


# --- Offline trip pass — a downloadable PDF that works with no signal -------- #


class TripExport(BaseModel):
    results: dict[str, Any]
    title: str | None = None


@app.post(f"{settings.api_prefix}/trip/export/pdf", tags=["trip"])
async def trip_export_pdf(body: TripExport) -> StreamingResponse:
    """Render the open trip to a self-contained PDF the traveller can save and
    open offline (no signal needed on the ground)."""
    import io

    from app.tools.trip_pdf import build_trip_pdf

    dest = ((body.results.get("chief") or {}).get("data") or {}).get("destination")
    title = (body.title or (f"{dest} trip" if dest else "Your Trip"))[:120]
    try:
        pdf = build_trip_pdf(body.results, title=title)
    except Exception as exc:  # noqa: BLE001
        logger.warning("trip PDF export failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not build the trip PDF.")
    safe = "".join(c for c in title if c.isalnum() or c in " -_").strip().replace(" ", "-") or "trip"
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'},
    )


# --- Per-place video — a real-life look at a spot (YouTube) ----------------- #


@app.get(f"{settings.api_prefix}/places/video", tags=["places"])
async def place_video(q: str, city: str = "") -> dict[str, object]:
    """Resolve a short real-life video for a place. Uses the YouTube Data API to
    return the top matching video; falls back to a YouTube search deep-link when
    no key/quota (so the button always leads somewhere). Cached 12h by the tool.
    """
    from urllib.parse import quote

    from app.mapping import _resolve_city
    from app.tools import youtube

    query = f"{q} {_resolve_city(city)}".strip()  # IATA (NRT) → city (Tokyo)
    vids = await youtube.search_videos(f"{query} travel", max_results=1)
    if vids:
        v = vids[0]
        return {
            "url": f"https://www.youtube.com/watch?v={v['video_id']}",
            "title": v.get("title"),
            "thumbnail": v.get("thumbnail"),
            "source": "youtube",
        }
    return {
        "url": f"https://www.youtube.com/results?search_query={quote(query + ' travel')}",
        "title": None,
        "source": "search",
    }


@app.get(f"{settings.api_prefix}/places/image", tags=["places"])
async def place_image(q: str, city: str = "") -> dict[str, object]:
    """A representative photo thumbnail for a place — keyless via Openverse
    (CC-licensed image search), falling back to the Wikipedia lead image. Cached
    24h so a card only ever resolves once."""
    from app.mapping import _resolve_city
    from app.tools.photos import place_photo

    query = f"{q} {_resolve_city(city)}".strip()  # IATA (NRT) → city (Tokyo)
    return {"image": await place_photo(query)}


# --------------------------------------------------------------------------- #
# Scopes - the Command Center presets
# --------------------------------------------------------------------------- #


@app.get(f"{settings.api_prefix}/scopes", tags=["planning"])
async def list_scopes() -> list[dict[str, object]]:
    """Preset scopes: what each one runs, and how long it should take."""
    return scopes.catalogue()


#: Country → suggested cities, used only to ask "which city?" when a prompt names
#: a whole country but no city (a flight needs an airport).
_CLARIFY_COUNTRIES: dict[str, dict[str, object]] = {
    "japan": {"label": "Japan", "cities": ["Tokyo", "Osaka", "Kyoto", "Fukuoka", "Sapporo"]},
    "thailand": {"label": "Thailand", "cities": ["Bangkok", "Phuket", "Chiang Mai"]},
    "indonesia": {"label": "Indonesia", "cities": ["Bali (Denpasar)", "Jakarta", "Surabaya"]},
    "malaysia": {"label": "Malaysia", "cities": ["Kuala Lumpur", "Penang", "Kota Kinabalu", "Langkawi"]},
    "south korea": {"label": "South Korea", "cities": ["Seoul", "Busan", "Jeju"]},
    "korea": {"label": "South Korea", "cities": ["Seoul", "Busan", "Jeju"]},
    "vietnam": {"label": "Vietnam", "cities": ["Ho Chi Minh City", "Hanoi", "Da Nang"]},
    "china": {"label": "China", "cities": ["Shanghai", "Beijing", "Guangzhou", "Chengdu"]},
    "taiwan": {"label": "Taiwan", "cities": ["Taipei", "Kaohsiung"]},
    "philippines": {"label": "Philippines", "cities": ["Manila", "Cebu"]},
    "australia": {"label": "Australia", "cities": ["Sydney", "Melbourne", "Brisbane"]},
    "india": {"label": "India", "cities": ["Delhi", "Mumbai", "Bangalore"]},
    "united kingdom": {"label": "UK", "cities": ["London", "Manchester", "Edinburgh"]},
    "france": {"label": "France", "cities": ["Paris", "Nice", "Lyon"]},
    "italy": {"label": "Italy", "cities": ["Rome", "Milan", "Venice"]},
    "turkey": {"label": "Turkey", "cities": ["Istanbul", "Antalya"]},
    "uae": {"label": "UAE", "cities": ["Dubai", "Abu Dhabi"]},
    "brazil": {"label": "Brazil", "cities": ["Rio de Janeiro", "São Paulo", "Brasília"]},
    "switzerland": {"label": "Switzerland", "cities": ["Zurich", "Geneva", "Interlaken", "Lucerne"]},
    "germany": {"label": "Germany", "cities": ["Berlin", "Munich", "Frankfurt"]},
    "spain": {"label": "Spain", "cities": ["Barcelona", "Madrid", "Seville"]},
    "netherlands": {"label": "Netherlands", "cities": ["Amsterdam", "Rotterdam"]},
    "portugal": {"label": "Portugal", "cities": ["Lisbon", "Porto"]},
    "greece": {"label": "Greece", "cities": ["Athens", "Santorini", "Mykonos"]},
    "austria": {"label": "Austria", "cities": ["Vienna", "Salzburg"]},
    "saudi arabia": {"label": "Saudi Arabia", "cities": ["Riyadh", "Jeddah", "Makkah"]},
    "qatar": {"label": "Qatar", "cities": ["Doha"]},
    "egypt": {"label": "Egypt", "cities": ["Cairo", "Hurghada"]},
    "morocco": {"label": "Morocco", "cities": ["Marrakech", "Casablanca", "Fes"]},
    "cambodia": {"label": "Cambodia", "cities": ["Siem Reap", "Phnom Penh"]},
    "sri lanka": {"label": "Sri Lanka", "cities": ["Colombo", "Kandy"]},
    "nepal": {"label": "Nepal", "cities": ["Kathmandu", "Pokhara"]},
    "new zealand": {"label": "New Zealand", "cities": ["Auckland", "Queenstown", "Wellington"]},
    "united states": {"label": "USA", "cities": ["New York", "Los Angeles", "San Francisco"]},
    "usa": {"label": "USA", "cities": ["New York", "Los Angeles", "San Francisco"]},
    "canada": {"label": "Canada", "cities": ["Toronto", "Vancouver", "Montreal"]},
}


class ClarifyRequest(BaseModel):
    goal: str
    scope: str


_MONTHS = (
    "january february march april may june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec"
).split()


def _date_suggestions(goal: str) -> list[dict[str, str]]:
    """A few sensible date ranges when the traveller gave none — sized to the
    duration in the goal ('4 days'), so the plan has real dates to work with."""
    from datetime import date, timedelta

    m = re.search(r"(\d+)\s*(?:day|days|d|night|nights)", goal.lower())
    span = max(1, min(int(m.group(1)) if m else 4, 21)) - 1  # nights between check-in/out
    today = date.today()

    def _fwd(days: int) -> tuple[str, str]:
        start = today + timedelta(days=days)
        return start.isoformat(), (start + timedelta(days=span)).isoformat()

    sat_offset = (5 - today.weekday()) % 7 or 7  # next Saturday
    picks = [
        ("This coming weekend", *_fwd(sat_offset)),
        ("In 2 weeks", *_fwd(14)),
        ("Next month", *_fwd(30)),
    ]
    return [{"label": lbl, "start_date": s, "end_date": e} for lbl, s, e in picks]


async def _country_only_llm(goal: str) -> dict[str, object] | None:
    """Fallback for a country we don't have hard-coded (Switzerland, Kenya, …):
    ask the model whether the destination is a whole COUNTRY and, if so, its top
    cities — so ANY "3 days in <country>" goal gets a city prompt and the flight
    search targets a real airport instead of a country."""
    from app.core import llm

    try:
        raw = await llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Decide if a trip goal's DESTINATION is an entire country or region rather than a "
                        'specific city. If country-only, return {"country_only": true, "country": "Name", '
                        '"cities": [up to 5 major traveller cities]}. If it names a city, a non-place, or no '
                        'clear destination, return {"country_only": false}. JSON only.'
                    ),
                },
                {"role": "user", "content": goal[:400]},
            ],
            response_format={"type": "json_object"},
            agent="chief",
        )
        import json as _json

        data = _json.loads(raw)
        if data.get("country_only") and isinstance(data.get("cities"), list):
            cities = [str(c) for c in data["cities"] if c][:6]
            if cities:
                return {"country": str(data.get("country") or "there"), "cities": cities, "recommended": cities[0]}
    except Exception as exc:  # noqa: BLE001 — clarify is best-effort
        logger.info("country-only LLM fallback failed: %s", exc)
    return None


@app.post(f"{settings.api_prefix}/plan/clarify", tags=["planning"])
async def plan_clarify(request: ClarifyRequest) -> dict[str, object]:
    """Check a prompt before running: does it need an origin, a city for a
    country-only destination, or dates? Drives the just-in-time clarification
    popup so the CTA is always clickable and questions appear only when needed."""
    scope = scopes.get(request.scope)
    needs_flights = bool(scope and "route" in scope.inputs)
    needs_dates = bool(scope and ("dates" in scope.inputs or "date" in scope.inputs))
    text = request.goal.lower()

    parsed = goal_parser.parse_goal(request.goal)
    origin = parsed.get("origin")
    has_from = bool(re.search(r"\bfrom\s+[a-z0-9]", text))
    needs_origin = needs_flights and not origin and not has_from

    # If the parser already resolved a specific destination city (e.g. "chengdu
    # China" -> CTU), never ask "which city?" — the traveller named one, even if
    # it isn't in our short per-country pick-list.
    resolved_city = bool(parsed.get("destination"))
    country_only: dict[str, object] | None = None
    for key, info in _CLARIFY_COUNTRIES.items():
        if not resolved_city and re.search(rf"\b{re.escape(key)}\b", text):
            cities = info["cities"]
            named_city = any(str(c).split(" (")[0].lower() in text for c in cities)  # type: ignore[union-attr]
            if not named_city:
                country_only = {
                    "country": info["label"],
                    "cities": cities,
                    "recommended": cities[0],  # the agent's default pick if "You suggest"
                }
            break

    # Generic fallback for a country not in the table (Switzerland, Kenya, …):
    # only when nothing else pinned a destination, so a bare "3 days Switzerland"
    # still gets a city prompt (and Atlas a real airport) instead of searching a
    # whole country and returning no inventory. Asked together with origin/dates.
    if country_only is None and not resolved_city and needs_flights:
        country_only = await _country_only_llm(request.goal)

    # Suggest dates when the plan wants them and the goal names none. Detect an
    # existing date via the parser (handles explicit dates + relative phrases
    # like "next month") plus a word-boundary month check — a substring match
    # wrongly saw "dec" in "decide" and skipped the question.
    month_re = re.compile(r"\b(?:" + "|".join(_MONTHS) + r")\b")
    has_date = bool(parsed.get("start_date")) or bool(month_re.search(text))
    date_suggestions = _date_suggestions(request.goal) if (needs_dates or needs_flights) and not has_date else []

    return {
        "needs_clarification": bool(needs_origin or country_only or date_suggestions),
        "needs_origin": needs_origin,
        "country_only": country_only,
        "date_suggestions": date_suggestions,
    }


@app.get(f"{settings.api_prefix}/plan/nearby-cities", tags=["planning"])
async def nearby_cities(destination: str = "") -> dict[str, object]:
    """Other cities in the same country as `destination` — powers the results
    'not this city? try …' re-plan chips. Map-first, LLM fallback for anywhere."""
    dest = destination.strip()
    if not dest:
        return {"country": None, "cities": []}
    low = dest.lower().split(",")[0].strip()
    for key, info in _CLARIFY_COUNTRIES.items():
        cities = [str(c).split(" (")[0] for c in info["cities"]]  # type: ignore[union-attr]
        if key in low or any(low == c.lower() for c in cities):
            return {"country": info["label"], "cities": [c for c in cities if c.lower() != low][:6]}
    try:
        from app.core import llm

        raw = await llm.complete(
            [
                {"role": "system", "content": "Return ONLY JSON {\"country\":\"...\",\"cities\":[up to 6 other notable travel cities in the SAME country as the given place, excluding it]}"},
                {"role": "user", "content": dest},
            ],
            response_format={"type": "json_object"}, agent="chief",
        )
        import json as _json

        data = _json.loads(raw)
        return {"country": data.get("country"), "cities": [str(c) for c in (data.get("cities") or [])][:6]}
    except Exception as exc:  # noqa: BLE001
        logger.info("nearby-cities fell back: %s", exc)
        return {"country": None, "cities": []}


_SOCIAL_URL_RE = re.compile(
    r"https?://\S*(?:tiktok\.com|instagram\.com|instagr\.am|youtube\.com|youtu\.be|"
    r"twitter\.com|x\.com|facebook\.com|fb\.watch|vm\.tiktok\.com|vt\.tiktok\.com)\S*",
    re.I,
)


class SocialSeedRequest(BaseModel):
    goal: str = ""
    url: str | None = None


@app.post(f"{settings.api_prefix}/plan/social-seed", tags=["planning"])
async def plan_social_seed(body: SocialSeedRequest) -> dict[str, object]:
    """Read a social-media link (TikTok / IG / YT / X / FB) and return a trip
    seed — a real goal + destination — so the Command Center can plan straight
    from a pasted link. Seed only; the caller launches the plan through the
    normal job flow so results land in the usual results view."""
    url = body.url
    if not url:
        match = _SOCIAL_URL_RE.search(body.goal or "")
        url = match.group(0) if match else None
    if not url:
        return {"seed": None, "error": "No social link found."}
    from app.tools import social

    # Pass the whole prompt as text too, so extra words the traveller added
    # ("3 days, halal food") enrich the seed alongside the post's caption.
    seed = await social.extract_trip_seed(url=url, text=body.goal or None)
    if seed.get("error"):
        return {"seed": None, "error": seed["error"]}
    return {"seed": seed, "error": None}


# --------------------------------------------------------------------------- #
# Flight booking flow (Atlas)
# --------------------------------------------------------------------------- #


class EnvironmentRequest(BaseModel):
    environment: Literal["sandbox", "production"] = "sandbox"


class BookingStart(BaseModel):
    offer_id: str
    route: str | None = None
    depart_date: date | None = None
    travellers: int = 1
    total_amount: float | None = None
    currency: str | None = None
    environment: Literal["sandbox", "production"] = "sandbox"
    trip_id: str | None = None
    offer_snapshot: dict[str, object] = {}


class BookingVerify(BaseModel):
    accept_price_change: bool = False


class Passenger(BaseModel):
    """One passenger. Sent straight to the CLI and never persisted."""

    given_name: str
    surname: str
    date_of_birth: str
    gender: Literal["male", "female"] | None = None
    nationality: str | None = None
    passport_number: str | None = None
    passport_expiry: str | None = None
    passenger_type: Literal["adult", "child", "infant"] = "adult"
    email: str | None = None
    phone: str | None = None


class BookingOrder(BaseModel):
    passengers: list[Passenger]
    seat_policy: str | None = None


@app.get(f"{settings.api_prefix}/flights/atlas/status", tags=["flights"])
async def atlas_status() -> dict[str, object]:
    """Is the Atlas CLI installed, authorised, and in which environment?"""
    return await booking_flow.atlas_status()


@app.post(f"{settings.api_prefix}/flights/atlas/environment", tags=["flights"])
async def atlas_set_environment(request: EnvironmentRequest) -> dict[str, object]:
    """Switch Atlas between sandbox and production."""
    try:
        return await booking_flow.set_environment(request.environment)
    except booking_flow.BookingFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/flights/atlas/authorize", tags=["flights"])
async def atlas_authorize() -> dict[str, object]:
    """Begin browser authorisation; returns the URL to open."""
    try:
        return await booking_flow.begin_authorization()
    except booking_flow.BookingFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/flights/atlas/authorize/poll", tags=["flights"])
async def atlas_authorize_poll() -> dict[str, object]:
    try:
        return await booking_flow.poll_authorization()
    except booking_flow.BookingFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(f"{settings.api_prefix}/flights/booking/start", tags=["flights"])
async def booking_start(request: BookingStart) -> dict[str, object]:
    """Open a booking for a chosen offer."""
    return await booking_flow.start(
        offer_id=request.offer_id,
        route=request.route,
        depart_date=request.depart_date,
        travellers=request.travellers,
        total_amount=request.total_amount,
        currency=request.currency,
        environment=request.environment,
        trip_id=request.trip_id,
        offer_snapshot=dict(request.offer_snapshot),
    )


@app.post(f"{settings.api_prefix}/flights/booking/{{booking_row_id}}/verify", tags=["flights"])
async def booking_verify(booking_row_id: str, request: BookingVerify) -> dict[str, object]:
    """Re-price and confirm. A price increase stops here unless accepted."""
    try:
        return await booking_flow.verify(
            booking_row_id, accept_price_change=request.accept_price_change
        )
    except booking_flow.BookingFlowError as exc:
        raise HTTPException(
            status_code=409, detail={"code": exc.code, "message": str(exc)}
        ) from exc


@app.post(f"{settings.api_prefix}/flights/booking/{{booking_row_id}}/order", tags=["flights"])
async def booking_order(booking_row_id: str, request: BookingOrder) -> dict[str, object]:
    """Create the order. Passenger details are not stored."""
    try:
        return await booking_flow.create_order(
            booking_row_id,
            [p.model_dump(exclude_none=True) for p in request.passengers],
            seat_policy=request.seat_policy,
        )
    except booking_flow.BookingFlowError as exc:
        raise HTTPException(
            status_code=409, detail={"code": exc.code, "message": str(exc)}
        ) from exc


@app.post(f"{settings.api_prefix}/flights/booking/{{booking_row_id}}/pay", tags=["flights"])
async def booking_pay(booking_row_id: str) -> dict[str, object]:
    """Pay from the Atlas balance. A confirmation ID is single-use."""
    try:
        return await booking_flow.pay(booking_row_id)
    except booking_flow.BookingFlowError as exc:
        raise HTTPException(
            status_code=409, detail={"code": exc.code, "message": str(exc)}
        ) from exc


@app.get(f"{settings.api_prefix}/flights/booking/{{booking_row_id}}", tags=["flights"])
async def booking_get(booking_row_id: str) -> dict[str, object]:
    record = await bookings.get(booking_row_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return record


@app.post(f"{settings.api_prefix}/flights/booking/{{booking_row_id}}/status", tags=["flights"])
async def booking_status(booking_row_id: str) -> dict[str, object]:
    """Poll ticketing (up to 120s), or query the order later."""
    try:
        return await booking_flow.status(booking_row_id)
    except booking_flow.BookingFlowError as exc:
        raise HTTPException(
            status_code=409, detail={"code": exc.code, "message": str(exc)}
        ) from exc


class AutoRecoverRequest(BaseModel):
    #: Force a status for a deterministic demo ("delayed" | "cancelled" |
    #: "on_time"); omit to check the real flight status.
    simulate: str | None = None
    #: A delay this long (minutes) or a cancellation triggers recovery.
    threshold_minutes: int = 90
    #: False = preview only (detect + choose best alternative, no refund/rebook).
    execute: bool = True


@app.post(f"{settings.api_prefix}/flights/booking/{{booking_row_id}}/auto-recover", tags=["flights"])
async def booking_auto_recover(booking_row_id: str, request: AutoRecoverRequest) -> dict[str, object]:
    """Autonomous disruption recovery for a booked flight: detect a delay/
    cancellation, pick the best alternative, refund the old booking and book the
    replacement — returning a step-by-step report of everything done."""
    try:
        return await auto_rebook.auto_recover(
            booking_row_id,
            simulate=request.simulate,
            threshold_minutes=request.threshold_minutes,
            execute=request.execute,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# History - past searches and bookings
# --------------------------------------------------------------------------- #


@app.get(f"{settings.api_prefix}/history/searches", tags=["history"])
async def history_searches(limit: int = 50, scope: str | None = None) -> list[dict[str, object]]:
    """Past runs, newest first."""
    return await history.list_entries(limit=limit, scope=scope)


@app.get(f"{settings.api_prefix}/history/searches/{{entry_id}}", tags=["history"])
async def history_search(entry_id: str) -> dict[str, object]:
    """One past run including its full result, so it can be reopened."""
    entry = await history.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="History entry not found")
    return entry


@app.delete(f"{settings.api_prefix}/history/searches/{{entry_id}}", tags=["history"])
async def history_delete(entry_id: str) -> dict[str, object]:
    if not await history.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="History entry not found")
    return {"deleted": True}


@app.get(f"{settings.api_prefix}/history/bookings", tags=["history"])
async def history_bookings(limit: int = 50) -> list[dict[str, object]]:
    """Flight bookings, newest first."""
    return await bookings.history(limit=limit)
