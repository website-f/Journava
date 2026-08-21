"""Journava FastAPI application — hosts the orchestrator and all agents (spec §5)."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

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
from app.saved import router as saved_router
from app.shared import router as shared_router
from app.supplier.ai import router as supplier_ai_router
from app.supplier.router import router as supplier_router
from app.brain import bookings, gnosion_client, history, outcomes, trip_store
from app.brain.demo_trip import get_demo_trip
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
from app.graph import booking_flow, scopes
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
    """Every ~6h, ping managers about upcoming check-ins (best-effort)."""
    import asyncio

    from app.bookings import send_due_reminders

    while True:
        try:
            await asyncio.sleep(6 * 3600)
            await send_due_reminders()
        except asyncio.CancelledError:  # noqa: PERF203
            break
        except Exception as exc:  # noqa: BLE001
            logger.info("reminder loop error: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Warm the optional dependencies; none of them are required to boot."""
    import asyncio

    logger.info("Journava API starting (%s)", settings.environment)
    await db.init_schema()
    await auth_store.seed_demo_users()
    await cache.get_redis()
    reminder_task = asyncio.create_task(_reminder_loop())
    # Restore the last trip from durable storage. Only seed the Venice demo trip
    # in demo mode (SEED_DEMO_USERS) — in production My Trip must stay empty until
    # the traveller adds one, never show a trip they didn't create.
    if await trip_store.load_trip_durable() is not None:
        logger.info("Active trip restored from durable storage")
    elif settings.seed_demo_users:
        trip_store.save_trip(get_demo_trip())
        logger.info("Demo trip seeded (Venice 7-day)")
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
    if trip is None:
        return {"trip": None}
    return {"trip": trip}


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
    "china": {"label": "China", "cities": ["Shanghai", "Beijing", "Guangzhou"]},
    "taiwan": {"label": "Taiwan", "cities": ["Taipei", "Kaohsiung"]},
    "philippines": {"label": "Philippines", "cities": ["Manila", "Cebu"]},
    "australia": {"label": "Australia", "cities": ["Sydney", "Melbourne", "Brisbane"]},
    "india": {"label": "India", "cities": ["Delhi", "Mumbai", "Bangalore"]},
    "united kingdom": {"label": "UK", "cities": ["London", "Manchester"]},
    "france": {"label": "France", "cities": ["Paris", "Nice"]},
    "italy": {"label": "Italy", "cities": ["Rome", "Milan", "Venice"]},
    "turkey": {"label": "Turkey", "cities": ["Istanbul", "Antalya"]},
    "uae": {"label": "UAE", "cities": ["Dubai", "Abu Dhabi"]},
    "brazil": {"label": "Brazil", "cities": ["Rio de Janeiro", "São Paulo", "Brasília"]},
}


class ClarifyRequest(BaseModel):
    goal: str
    scope: str


@app.post(f"{settings.api_prefix}/plan/clarify", tags=["planning"])
async def plan_clarify(request: ClarifyRequest) -> dict[str, object]:
    """Check a prompt before running: does it need an origin, or a city for a
    country-only destination? Drives the just-in-time clarification popup so the
    CTA is always clickable and questions appear only when something's missing."""
    scope = scopes.get(request.scope)
    needs_flights = bool(scope and "route" in scope.inputs)
    text = request.goal.lower()

    parsed = goal_parser.parse_goal(request.goal)
    origin = parsed.get("origin")
    has_from = bool(re.search(r"\bfrom\s+[a-z0-9]", text))
    needs_origin = needs_flights and not origin and not has_from

    country_only: dict[str, object] | None = None
    for key, info in _CLARIFY_COUNTRIES.items():
        if re.search(rf"\b{re.escape(key)}\b", text):
            cities = info["cities"]
            named_city = any(str(c).split(" (")[0].lower() in text for c in cities)  # type: ignore[union-attr]
            if not named_city:
                country_only = {"country": info["label"], "cities": cities}
            break

    return {
        "needs_clarification": bool(needs_origin or country_only),
        "needs_origin": needs_origin,
        "country_only": country_only,
    }


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
