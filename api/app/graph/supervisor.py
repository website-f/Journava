"""LangGraph supervisor — Chief Agent + specialist nodes (spec §5).

Topology (the reconciliation pattern):

    chief ─┬─► flight    ─┐
           ├─► hotel      ├─► budget ─► itinerary ─► memory ─► END
           ├─► research   │
           └─► weather_risk ┘

Phase 0 builds the real graph with the 8 nodes wired and streaming; each node
still returns its stub result. Phase 1 fills in the node bodies, Phase 2 adds
the Critic/Reflexion loop between the fan-out and `budget`.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, TypedDict

from app.agents import REGISTRY
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm, sse

#: Specialists that run concurrently after the Chief delegates.
PARALLEL_NODES = ("flight", "hotel", "research", "weather_risk")
#: Then these run in order, each consuming the previous results.
SEQUENTIAL_NODES = ("budget", "itinerary", "memory")

#: Minimum score before the Critic triggers a retry.
CRITIC_THRESHOLD = 0.6
CRITIC_PROMPT = """You are the Journava Critic agent. Score these results against the goal.

GOAL: {goal}

RESULTS SUMMARY:
{summary}

Respond in JSON only:
{{"score": 0.0-1.0, "weakest_agent": "flight|hotel|research|weather_risk", "critique": "brief reason"}}"""


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


def build_graph() -> Any:
    """Compile the supervisor graph. Returns None if langgraph is unavailable."""
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:  # pragma: no cover - Phase 0 boots without langgraph
        return None

    graph = StateGraph(GraphState)

    for slug in ("chief", *PARALLEL_NODES, *SEQUENTIAL_NODES):
        graph.add_node(slug, _node(slug))

    graph.add_edge(START, "chief")

    # Fan out from the Chief to the specialists, then fan back in.
    for slug in PARALLEL_NODES:
        graph.add_edge("chief", slug)
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
    for slug in PARALLEL_NODES:
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
    """
    compiled = build_graph()
    state: GraphState = {"request": request, "profile": profile, "results": {}}

    if compiled is not None:
        final = await compiled.ainvoke(state)
        results = final["results"]
    else:
        sse.publish("chief", "working", "Running without langgraph (fallback path)")
        results = {}

        chief = await REGISTRY["chief"](request, profile)
        results["chief"] = chief.model_dump(mode="json")

        parallel = await asyncio.gather(
            *(REGISTRY[slug](request, profile, caused_by="chief") for slug in PARALLEL_NODES)
        )
        for slug, result in zip(PARALLEL_NODES, parallel, strict=True):
            results[slug] = result.model_dump(mode="json")

    # --- Critic / Reflexion loop (Phase 3) ---
    # Score results against goal; re-run weakest agent if below threshold.
    sse.publish("chief", "working", "Critic: scoring results")
    score, weakest, critique = await _critique(request, results)
    sse.publish("chief", "active", f"Critic: score={score:.2f} — {'passed' if score >= CRITIC_THRESHOLD else 'refinement needed'}")

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

    # --- Sequential nodes (budget → itinerary → memory) ---
    for slug in SEQUENTIAL_NODES:
        result = await REGISTRY[slug](request, profile, caused_by="chief", context=results)
        results[slug] = result.model_dump(mode="json")

    return results
