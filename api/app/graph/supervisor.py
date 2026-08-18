"""LangGraph supervisor — Chief Agent + specialist nodes (spec §5).

3-Tier topology (full 20-agent roster):

    chief ─┬─► flight         ─┐
           ├─► hotel           │
           ├─► research        │
           ├─► weather_risk    │
           ├─► visa            │
           ├─► emergency       ├─► [CRITIC] ─┬─► concierge      ─┐
           ├─► crowd           │             ├─► transport       │
           └─► risk_advisory  ─┘             ├─► sustainability  │
                                             ├─► payment         │
                                             ├─► insurance       ├─► budget ─► itinerary ─► memory ─► END
                                             ├─► recommendation  │
                                             ├─► analytics       │
                                             ├─► language        │
                                             └─► shopping       ─┘
"""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any, TypedDict

from app.agents import REGISTRY
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm, sse

# --------------------------------------------------------------------------- #
# Cancel mechanism
# --------------------------------------------------------------------------- #

_cancelled = False


def cancel_run() -> None:
    """Request cancellation of the current planning run."""
    global _cancelled
    _cancelled = True


def reset_cancel() -> None:
    """Reset the cancellation flag (called at start of each run)."""
    global _cancelled
    _cancelled = False


def is_cancelled() -> bool:
    return _cancelled


# --------------------------------------------------------------------------- #
# Phase timing estimates (seconds) — used by the frontend for ETA
# --------------------------------------------------------------------------- #

PHASE_ESTIMATES: dict[str, int] = {
    "tier1": 40,
    "critic": 8,
    "tier2": 30,
    "tier3": 20,
}
TOTAL_ESTIMATE = sum(PHASE_ESTIMATES.values())  # ~98s

#: Tier 1 — core intelligence (8 parallel agents after Chief).
PARALLEL_NODES = (
    "flight", "hotel", "research", "weather_risk",
    "visa", "emergency", "crowd", "risk_advisory",
)
#: Tier 2 — enrichment (9 parallel agents, run after the Critic scores).
ENRICHMENT_NODES = (
    "concierge", "transport", "sustainability", "payment",
    "insurance", "recommendation", "analytics", "language", "shopping",
)
#: Tier 3 — assembly (3 sequential, each consuming previous results).
SEQUENTIAL_NODES = ("budget", "itinerary", "memory")

#: Minimum score before the Critic triggers a retry.
CRITIC_THRESHOLD = 0.6
CRITIC_PROMPT = """You are the Journava Critic agent. Score these results against the goal.

GOAL: {goal}

RESULTS SUMMARY:
{summary}

Respond in JSON only:
{{"score": 0.0-1.0, "weakest_agent": "flight|hotel|research|weather_risk|visa|emergency|crowd|risk_advisory", "critique": "brief reason"}}"""


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Reducer so parallel branches can write results without clobbering."""
    return {**left, **right}


class GraphState(TypedDict):
    request: TripRequest
    profile: TravelerProfile
    results: Annotated[dict[str, Any], _merge]


def _node(slug: str):
    """Wrap a registered agent as a LangGraph node."""

    async def run_node(state: GraphState) -> dict[str, Any]:
        agent = REGISTRY[slug]
        # Sequential nodes receive accumulated results as context.
        context = state["results"] if slug in SEQUENTIAL_NODES else None
        result: AgentResult = await agent(
            state["request"],
            state["profile"],
            caused_by="chief" if slug != "chief" else None,
            context=context,
        )
        return {"results": {slug: result.model_dump(mode="json")}}

    run_node.__name__ = f"node_{slug}"
    return run_node


def _phase_event(
    phase: str,
    label: str,
    status: str,
    *,
    steps: int = 0,
    elapsed: float = 0,
) -> None:
    """Publish a phase-level SSE event with progress metadata."""
    remaining_secs = max(0, TOTAL_ESTIMATE - int(elapsed))
    sse.publish(
        "system", status, label,
        data={
            "phase": phase,
            "steps_total": steps,
            "elapsed_s": round(elapsed, 1),
            "eta_s": remaining_secs,
        },
    )


def build_graph() -> Any:
    """Compile the supervisor graph. Returns None if langgraph is unavailable."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:  # pragma: no cover - Phase 0 boots without langgraph
        return None

    graph = StateGraph(GraphState)

    for slug in ("chief", *PARALLEL_NODES, *ENRICHMENT_NODES, *SEQUENTIAL_NODES):
        graph.add_node(slug, _node(slug))

    graph.add_edge(START, "chief")

    # Fan out from the Chief to Tier 1 specialists.
    for slug in PARALLEL_NODES:
        graph.add_edge("chief", slug)

    # Tier 1 -> first enrichment node (graph collects all Tier 1 via fan-in).
    # LangGraph requires a single target after fan-in; we route through the
    # first enrichment node as a gateway (enrichment runs after critic anyway).
    for slug in PARALLEL_NODES:
        graph.add_edge(slug, ENRICHMENT_NODES[0])

    # Fan out enrichment (first -> rest).
    for slug in ENRICHMENT_NODES[1:]:
        graph.add_edge(ENRICHMENT_NODES[0], slug)

    # Enrichment fan-in -> budget (first sequential node).
    for slug in ENRICHMENT_NODES:
        graph.add_edge(slug, SEQUENTIAL_NODES[0])

    for current, following in zip(SEQUENTIAL_NODES, SEQUENTIAL_NODES[1:], strict=False):
        graph.add_edge(current, following)

    graph.add_edge(SEQUENTIAL_NODES[-1], END)

    return graph.compile()


async def _critique(
    request: TripRequest,
    results: dict[str, Any],
) -> tuple[float, str | None, str]:
    """Score the combined agent results against the goal.

    Returns (score, weakest_agent_slug, critique_text).
    """
    import json

    # Build a brief summary of what each agent produced
    lines = []
    for slug in (*PARALLEL_NODES, *ENRICHMENT_NODES):
        r = results.get(slug, {})
        status = r.get("status", "unknown")
        data_preview = str(r.get("data", {}))[:200]
        lines.append(f"- {slug}: status={status}, data={data_preview}")

    summary = "\n".join(lines)
    prompt = CRITIC_PROMPT.format(goal=request.goal, summary=summary)

    try:
        response = await llm.complete(
            [{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
            agent="critic",
        )
        parsed = json.loads(response)
        score = float(parsed.get("score", 1.0))
        weakest = parsed.get("weakest_agent")
        critique = parsed.get("critique", "")
        # Validate weakest agent
        if weakest and weakest not in PARALLEL_NODES:
            weakest = None
        return score, weakest, critique
    except Exception:  # noqa: BLE001
        return 1.0, None, ""  # If critic fails, assume results are fine


async def run_plan(
    request: TripRequest,
    profile: TravelerProfile,
) -> dict[str, Any]:
    """Execute a full planning run and return every agent's result.

    Falls back to a direct asyncio fan-out when langgraph isn't installed, so the
    endpoint behaves identically in a bare Phase 0 environment.

    Emits phase-level SSE events with step counts and ETA for the frontend
    live-log overlay. Supports cancellation via ``cancel_run()``.
    """
    reset_cancel()
    t0 = time.monotonic()

    compiled = build_graph()
    state: GraphState = {"request": request, "profile": profile, "results": {}}

    # Signal plan start
    sse.publish(
        "system", "working", "Plan started — 4 phases ahead",
        data={
            "phase": "start",
            "total_steps": (
                1 + len(PARALLEL_NODES) + 1 + len(ENRICHMENT_NODES) + len(SEQUENTIAL_NODES)
            ),
            "eta_s": TOTAL_ESTIMATE,
        },
    )

    if compiled is not None:
        final = await compiled.ainvoke(state)
        results = final["results"]
    else:
        results: dict[str, Any] = {}

        # Chief
        sse.publish("chief", "working", "Chief Agent is analyzing your request…")
        chief = await REGISTRY["chief"](request, profile)
        results["chief"] = chief.model_dump(mode="json")

        if is_cancelled():
            sse.publish("system", "idle", "Plan cancelled by user")
            return results

        # --- Tier 1: core intelligence (8 parallel) ---
        _phase_event("tier1", f"Tier 1: {len(PARALLEL_NODES)} core agents launching", "working",
                     steps=len(PARALLEL_NODES), elapsed=time.monotonic() - t0)
        parallel = await asyncio.gather(
            *(REGISTRY[slug](request, profile, caused_by="chief") for slug in PARALLEL_NODES)
        )
        for slug, result in zip(PARALLEL_NODES, parallel, strict=True):
            results[slug] = result.model_dump(mode="json")

    if is_cancelled():
        sse.publish("system", "idle", "Plan cancelled by user")
        return results

    # --- Critic / Reflexion loop (Phase 3) ---
    _phase_event("critic", "Critic: scoring Tier 1 results", "working",
                 steps=1, elapsed=time.monotonic() - t0)
    score, weakest, critique = await _critique(request, results)
    sse.publish(
        "chief", "active",
        f"Critic: score={score:.2f} — {'passed' if score >= CRITIC_THRESHOLD else 'refinement needed'}",
    )

    if score < CRITIC_THRESHOLD and weakest:
        sse.publish("chief", "working", f"Critic: re-running {weakest} — {critique}")
        try:
            improved = await REGISTRY[weakest](
                request, profile, caused_by="chief",
                context={**results, "critique": critique, "critic_score": score},
            )
            results[weakest] = improved.model_dump(mode="json")
            sse.publish(weakest, "active", "Critic refinement complete")
        except Exception:  # noqa: BLE001
            sse.publish("chief", "error", f"Critic retry failed for {weakest}")

    if is_cancelled():
        sse.publish("system", "idle", "Plan cancelled by user")
        return results

    # --- Tier 2: enrichment (9 parallel, after critic) ---
    _phase_event("tier2", f"Tier 2: {len(ENRICHMENT_NODES)} enrichment agents launching", "working",
                 steps=len(ENRICHMENT_NODES), elapsed=time.monotonic() - t0)
    enrichment = await asyncio.gather(
        *(REGISTRY[slug](request, profile, caused_by="chief", context=results) for slug in ENRICHMENT_NODES)
    )
    for slug, result in zip(ENRICHMENT_NODES, enrichment, strict=True):
        results[slug] = result.model_dump(mode="json")

    if is_cancelled():
        sse.publish("system", "idle", "Plan cancelled by user")
        return results

    # --- Tier 3: assembly (budget → itinerary → memory) ---
    _phase_event("tier3", "Tier 3: assembling budget, itinerary & memory", "working",
                 steps=len(SEQUENTIAL_NODES), elapsed=time.monotonic() - t0)
    for slug in SEQUENTIAL_NODES:
        result = await REGISTRY[slug](request, profile, caused_by="chief", context=results)
        results[slug] = result.model_dump(mode="json")

    elapsed_total = round(time.monotonic() - t0, 1)
    sse.publish(
        "system", "active", f"Plan complete in {elapsed_total}s",
        data={"phase": "done", "elapsed_s": elapsed_total},
    )
    return results
