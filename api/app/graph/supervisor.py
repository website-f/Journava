"""LangGraph supervisor — Chief Agent + specialist nodes (spec §5).

4-phase topology. The Critic is a real **barrier node** between Tier 1 and
Tier 2, so a refinement it triggers actually influences everything downstream:

    START → chief ─┬─► flight         ─┐
                   ├─► hotel           │
                   ├─► research        │
                   ├─► weather_risk    │   ┌────────┐   ┌─► concierge      ─┐
                   ├─► visa            ├──►│ CRITIC │──►├─► transport       │
                   ├─► emergency       │   │barrier │   ├─► sustainability  │
                   ├─► crowd           │   └────────┘   ├─► payment         │
                   └─► risk_advisory  ─┘                ├─► insurance       ├─┐
                                                        ├─► recommendation  │ │
                                                        ├─► analytics       │ │
                                                        ├─► language        │ │
                                                        └─► shopping       ─┘ │
                                                                              │
              END ◄── memory ◄── budget ◄── itinerary ◄────────────────────────┘

Three invariants this module must preserve:

1. **Every agent runs exactly once per plan.** The compiled graph is the only
   executor when langgraph is installed; `_run_without_langgraph` mirrors it
   for environments where langgraph is absent. They never both run. The single
   exception is a Critic-triggered retry of one weak agent, which is the whole
   point of the Reflexion loop (§7 ②).
2. **A barrier is a barrier.** Fan-in must land on exactly one node so every
   upstream branch completes in the same superstep. Routing a fan-in through
   "the first node of the next tier" makes that node's successors fire twice.
3. **Tier 3 follows the data dependency**: `itinerary` produces the items and
   day count that `budget` aggregates, so itinerary runs *before* budget.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Annotated, Any, NotRequired, TypedDict

from app.agents import REGISTRY
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm, sse
from app.graph import scopes
from app.graph.scopes import Scope

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Topology
# --------------------------------------------------------------------------- #

#: Tier 1 — core intelligence (8 parallel agents after Chief).
PARALLEL_NODES = (
    "flight",
    "hotel",
    "research",
    "weather_risk",
    "visa",
    "emergency",
    "crowd",
    "risk_advisory",
)
#: Tier 2 — enrichment (9 parallel agents, run after the Critic barrier).
ENRICHMENT_NODES = (
    "concierge",
    "transport",
    "sustainability",
    "payment",
    "insurance",
    "recommendation",
    "analytics",
    "language",
    "shopping",
)
#: Tier 3 — assembly (sequential, each consuming previous results).
#: itinerary first: budget aggregates the itinerary's items and night count.
SEQUENTIAL_NODES = ("itinerary", "budget", "memory")

#: The Critic barrier node name (not a REGISTRY entry — it lives in this module).
CRITIC_NODE = "critic"

#: Which phase each node belongs to, for SSE progress reporting.
_PHASE_OF: dict[str, str] = {
    "chief": "chief",
    CRITIC_NODE: "critic",
    **{slug: "tier1" for slug in PARALLEL_NODES},
    **{slug: "tier2" for slug in ENRICHMENT_NODES},
    **{slug: "tier3" for slug in SEQUENTIAL_NODES},
}

#: Phase timing estimates (seconds) — the frontend turns these into an ETA.
PHASE_ESTIMATES: dict[str, int] = {
    "chief": 6,
    "tier1": 40,
    "critic": 8,
    "tier2": 30,
    "tier3": 20,
}
TOTAL_ESTIMATE = sum(PHASE_ESTIMATES.values())

_PHASE_LABEL: dict[str, str] = {
    "chief": "Chief Agent is analyzing your request…",
    "tier1": f"Tier 1: {len(PARALLEL_NODES)} core agents launching",
    "critic": "Critic: scoring Tier 1 results",
    "tier2": f"Tier 2: {len(ENRICHMENT_NODES)} enrichment agents launching",
    "tier3": "Tier 3: assembling itinerary, budget & memory",
}
_PHASE_STEPS: dict[str, int] = {
    "chief": 1,
    "tier1": len(PARALLEL_NODES),
    "critic": 1,
    "tier2": len(ENRICHMENT_NODES),
    "tier3": len(SEQUENTIAL_NODES),
}

#: Agent invocations in a clean run — asserted by tests/test_supervisor.py.
TOTAL_AGENT_INVOCATIONS = 1 + len(PARALLEL_NODES) + len(ENRICHMENT_NODES) + len(SEQUENTIAL_NODES)

#: Minimum score before the Critic triggers a retry.
CRITIC_THRESHOLD = 0.6
CRITIC_PROMPT = """You are the Journava Critic agent. Score these results against the goal.

GOAL: {goal}

RESULTS SUMMARY:
{summary}

Respond in JSON only:
{{"score": 0.0-1.0, "weakest_agent": "flight|hotel|research|weather_risk|visa|emergency|crowd|risk_advisory", "critique": "brief reason"}}"""


# --------------------------------------------------------------------------- #
# Run state: cancellation + phase clock
# --------------------------------------------------------------------------- #


class _RunClock:
    """Per-run wall clock and once-only phase announcer.

    `estimate` is the scope's own wall-clock guess, so a two-agent flight search
    doesn't advertise the 95-second ETA of a full trip.
    """

    def __init__(self, estimate: int = TOTAL_ESTIMATE) -> None:
        self.t0 = time.monotonic()
        self.announced: set[str] = set()
        self.cancelled = False
        self.estimate = estimate

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def announce(self, phase: str) -> None:
        """Publish a phase event the first time a node of that phase starts."""
        if phase in self.announced or phase not in _PHASE_LABEL:
            return
        self.announced.add(phase)
        sse.publish(
            "system",
            "working",
            _PHASE_LABEL[phase],
            data={
                "phase": phase,
                "steps_total": _PHASE_STEPS.get(phase, 0),
                "elapsed_s": round(self.elapsed(), 1),
                "eta_s": max(0, self.estimate - int(self.elapsed())),
            },
        )


#: The clock for the run currently in flight. Replaced at the start of each run.
_clock = _RunClock()


def cancel_run() -> None:
    """Request cancellation of the current planning run.

    Agents already in flight finish; every node that has not started yet is
    skipped, so the run winds down instead of being abandoned mid-graph.
    """
    _clock.cancelled = True


def reset_cancel() -> None:
    """Reset the cancellation flag."""
    _clock.cancelled = False


def is_cancelled() -> bool:
    return _clock.cancelled


# --------------------------------------------------------------------------- #
# Chief enrichment — the parsed goal must reach the specialists
# --------------------------------------------------------------------------- #


def apply_chief_enrichment(
    request: TripRequest,
    chief_result: dict[str, Any],
) -> TripRequest:
    """Fold the Chief's parsed fields into the request the specialists receive.

    Without this the Chief's LLM parsing is decorative: it resolves
    "7-day Venice trip for 2" into structured fields that nothing reads, and all
    20 specialists plan for `destination=None` — i.e. for "unknown".

    Validation (rather than `model_copy`) is deliberate: the Chief returns ISO
    date *strings*, which Pydantic coerces to `date` here.
    """
    enriched = (chief_result.get("data") or {}).get("enriched") or {}
    if not enriched:
        return request
    merged = {**request.model_dump(), **enriched}
    try:
        return TripRequest.model_validate(merged)
    except Exception as exc:  # noqa: BLE001 — a bad parse must never kill a run
        logger.warning("Chief enrichment rejected (%s); keeping original request", exc)
        return request


# --------------------------------------------------------------------------- #
# Graph state
# --------------------------------------------------------------------------- #


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Reducer so parallel branches can write results without clobbering."""
    return {**left, **right}


class GraphState(TypedDict):
    request: TripRequest
    profile: TravelerProfile
    results: Annotated[dict[str, Any], _merge]
    #: The scope's parallel agents — what the Critic is allowed to blame.
    critic_candidates: NotRequired[tuple[str, ...]]


def _node(slug: str):
    """Wrap a registered agent as a LangGraph node."""

    phase = _PHASE_OF.get(slug, "tier1")
    needs_context = slug in SEQUENTIAL_NODES or slug in ENRICHMENT_NODES

    async def run_node(state: GraphState) -> dict[str, Any]:
        if _clock.cancelled:
            return {}
        _clock.announce(phase)

        agent = REGISTRY[slug]
        result: AgentResult = await agent(
            state["request"],
            state["profile"],
            caused_by="chief" if slug != "chief" else None,
            context=state["results"] if needs_context else None,
        )
        update: dict[str, Any] = {"results": {slug: result.model_dump(mode="json")}}

        # The Chief is the only node that rewrites the request for everyone else.
        if slug == "chief":
            update["request"] = apply_chief_enrichment(state["request"], update["results"]["chief"])
        return update

    run_node.__name__ = f"node_{slug}"
    return run_node


async def _critique(
    request: TripRequest,
    results: dict[str, Any],
    candidates: tuple[str, ...] = PARALLEL_NODES,
) -> tuple[float, str | None, str]:
    """Score the combined Tier 1 results against the goal.

    Returns (score, weakest_agent_slug, critique_text). A failing critic scores
    1.0 so an unavailable LLM never blocks a plan.
    """
    lines: list[str] = []
    for slug in candidates:
        result = results.get(slug)
        if not result:
            continue
        lines.append(
            f"- {slug}: {result.get('summary', 'n/a')} | data={str(result.get('data', {}))[:200]}"
        )
    prompt = CRITIC_PROMPT.format(goal=request.goal, summary="\n".join(lines))

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
        if weakest not in candidates:
            weakest = None
        return score, weakest, parsed.get("critique", "")
    except Exception as exc:  # noqa: BLE001
        logger.info("Critic unavailable (%s) — passing Tier 1 through", exc)
        return 1.0, None, ""


async def _critic_node(state: GraphState) -> dict[str, Any]:
    """The Tier 1 → Tier 2 barrier: score, then refine the weakest agent.

    Being a real node (rather than a pass after the whole graph finished) is
    what makes the Reflexion loop meaningful — the refined result is present in
    `results` before any Tier 2 or Tier 3 agent reads it.
    """
    if _clock.cancelled:
        return {}
    _clock.announce("critic")

    request, results = state["request"], state["results"]
    candidates = tuple(state.get("critic_candidates") or PARALLEL_NODES)
    score, weakest, critique = await _critique(request, results, candidates)
    passed = score >= CRITIC_THRESHOLD
    sse.publish(
        "chief",
        "active",
        f"Critic: score={score:.2f} — {'passed' if passed else 'refinement needed'}",
        data={"score": score, "weakest_agent": weakest, "critique": critique},
    )

    update: dict[str, Any] = {
        "results": {
            CRITIC_NODE: {
                "agent": CRITIC_NODE,
                "summary": f"Critic score {score:.2f}",
                "options": [],
                "items": [],
                "applied_preferences": {},
                "warnings": [],
                "data": {
                    "score": score,
                    "weakest_agent": weakest,
                    "critique": critique,
                    "threshold": CRITIC_THRESHOLD,
                    "retried": False,
                },
            }
        }
    }

    if passed or not weakest:
        return update

    sse.publish("chief", "working", f"Critic: re-running {weakest} — {critique}")
    try:
        improved = await REGISTRY[weakest](
            request,
            state["profile"],
            caused_by=CRITIC_NODE,
            context={**results, "critique": critique, "critic_score": score},
        )
        update["results"][weakest] = improved.model_dump(mode="json")
        update["results"][CRITIC_NODE]["data"]["retried"] = True
        sse.publish(weakest, "active", "Critic refinement complete")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Critic retry of %s failed: %s", weakest, exc)
        sse.publish("chief", "error", f"Critic retry failed for {weakest}")
    return update


# --------------------------------------------------------------------------- #
# Graph construction
# --------------------------------------------------------------------------- #


def build_graph(scope: Scope | None = None) -> Any:
    """Compile a supervisor graph for `scope`. None if langgraph is unavailable.

    The graph is built per scope rather than once: a flights-only question should
    not instantiate 21 nodes and then skip 19 of them, because a skipped node is
    still a superstep and still shows up in the progress stream.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:  # pragma: no cover — the asyncio mirror covers this
        return None

    scope = scope or scopes.get(scopes.DEFAULT_SCOPE)
    parallel = scope.parallel_agents()
    sequential = scope.sequential_agents()
    # The Critic only earns a node when there is more than one result to weigh.
    use_critic = scope.use_critic and len(parallel) > 1

    graph = StateGraph(GraphState)
    graph.add_node("chief", _node("chief"))
    for slug in (*parallel, *sequential):
        graph.add_node(slug, _node(slug))
    if use_critic:
        graph.add_node(CRITIC_NODE, _critic_node)

    graph.add_edge(START, "chief")

    # Fan-in must land on exactly ONE node, or that node's successors fire in two
    # supersteps and everything downstream runs twice (see invariant 2).
    barrier = CRITIC_NODE if use_critic else (sequential[0] if sequential else None)

    if not parallel:
        # Degenerate scope: chief straight into the assembly chain, or to END.
        if sequential:
            graph.add_edge("chief", sequential[0])
        else:
            graph.add_edge("chief", END)
    else:
        for slug in parallel:
            graph.add_edge("chief", slug)
            if barrier is not None:
                graph.add_edge(slug, barrier)
            else:
                graph.add_edge(slug, END)

        if use_critic and sequential:
            graph.add_edge(CRITIC_NODE, sequential[0])
        elif use_critic:
            graph.add_edge(CRITIC_NODE, END)

    for current, following in zip(sequential, sequential[1:], strict=False):
        graph.add_edge(current, following)
    if sequential:
        graph.add_edge(sequential[-1], END)

    return graph.compile()


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #


async def run_plan(
    request: TripRequest,
    profile: TravelerProfile,
    scope: Scope | str | None = None,
) -> dict[str, Any]:
    """Execute one planning run for `scope` and return every agent's result.

    Exactly one executor runs: the compiled LangGraph when it is installed,
    otherwise the asyncio mirror.
    """
    global _clock

    resolved = scope if isinstance(scope, Scope) else scopes.get(scope)
    parallel = resolved.parallel_agents()
    sequential = resolved.sequential_agents()
    use_critic = resolved.use_critic and len(parallel) > 1
    total_agents = len(resolved.resolved_agents())

    _clock = _RunClock(estimate=resolved.estimate_seconds)

    sse.publish(
        "system",
        "working",
        f"{resolved.label} — {total_agents} agent(s) engaged",
        data={
            "phase": "start",
            "scope": resolved.slug,
            "scope_label": resolved.label,
            "total_steps": total_agents + (1 if use_critic else 0),
            "agents": list(resolved.resolved_agents()),
            "eta_s": resolved.estimate_seconds,
        },
    )

    compiled = build_graph(resolved)
    state: GraphState = {
        "request": request,
        "profile": profile,
        "results": {},
        "critic_candidates": parallel,
    }

    if compiled is not None:
        final = await compiled.ainvoke(state)
        results = final["results"]
    else:
        results = await _run_without_langgraph(state, parallel, sequential, use_critic)

    if _clock.cancelled:
        sse.publish("system", "idle", "Plan cancelled by user")
        return results

    results["_scope"] = {
        "slug": resolved.slug,
        "label": resolved.label,
        "panels": list(resolved.panels),
        "agents": list(resolved.resolved_agents()),
    }

    elapsed_total = round(_clock.elapsed(), 1)
    sse.publish(
        "system",
        "active",
        f"{resolved.label} complete in {elapsed_total}s",
        data={"phase": "done", "elapsed_s": elapsed_total, "scope": resolved.slug},
    )
    return results


async def _run_without_langgraph(
    state: GraphState,
    parallel: tuple[str, ...],
    sequential: tuple[str, ...],
    use_critic: bool,
) -> dict[str, Any]:
    """Mirror of the compiled graph for environments without langgraph.

    Same node set, same order, same barrier semantics — behaviour must not
    change with the dependency's presence.
    """
    results: dict[str, Any] = {}
    request, profile = state["request"], state["profile"]

    async def call(
        slug: str,
        *,
        context: dict[str, Any] | None = None,
        caused_by: str | None = "chief",
    ) -> None:
        if _clock.cancelled:
            return
        _clock.announce(_PHASE_OF.get(slug, "tier1"))
        result = await REGISTRY[slug](request, profile, caused_by=caused_by, context=context)
        results[slug] = result.model_dump(mode="json")

    # Chief — then fold its parsed fields into the request everyone else sees.
    await call("chief", caused_by=None)
    if _clock.cancelled:
        return results
    request = apply_chief_enrichment(request, results.get("chief", {}))

    if parallel:
        await asyncio.gather(*(call(slug) for slug in parallel))
        if _clock.cancelled:
            return results

    if use_critic:
        critic_update = await _critic_node(
            {
                "request": request,
                "profile": profile,
                "results": results,
                "critic_candidates": parallel,
            }
        )
        results.update(critic_update.get("results", {}))
        if _clock.cancelled:
            return results

    for slug in sequential:
        await call(slug, context=results)

    return results
