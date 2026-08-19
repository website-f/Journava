"""Capability catalog — one manifest across every pack.

The orchestrator and the UI should discover agents by *what they can do*, not by
a hardcoded list. This builds that view over both the travel roster and the task
agents, indexed by domain and by capability.

Travel-agent capability tags live here (rather than on all 21 classes) so the
manifest can be enriched without a 21-file edit; a class may still declare its
own `capabilities`, which win when present.
"""

from __future__ import annotations

from typing import Any

from app.agents import REGISTRY
from app.runtime.tasks import describe_task_agents

_TRAVEL_CAPS: dict[str, tuple[str, ...]] = {
    "chief": ("orchestration.plan", "task.decompose", "reconcile"),
    "flight": ("flight.search", "flight.book", "flight.reprice"),
    "hotel": ("hotel.search", "hotel.compare"),
    "research": ("web.research", "reviews.aggregate", "sentiment.analyze"),
    "weather_risk": ("weather.forecast", "risk.assess"),
    "visa": ("visa.requirements", "entry.rules"),
    "emergency": ("emergency.reroute", "safety.monitor"),
    "crowd": ("crowd.predict",),
    "risk_advisory": ("risk.score", "trust.verify"),
    "concierge": ("booking.reserve", "concierge.assist"),
    "transport": ("transport.route", "multimodal.plan"),
    "sustainability": ("carbon.estimate", "eco.suggest"),
    "payment": ("payment.checkout", "expense.split"),
    "insurance": ("insurance.quote", "claims.prepare"),
    "recommendation": ("recommend.personalized",),
    "analytics": ("analytics.report",),
    "language": ("translate.text", "culture.brief"),
    "shopping": ("shopping.find", "dutyfree.compare"),
    "budget": ("budget.track", "budget.optimize"),
    "itinerary": ("itinerary.assemble",),
    "memory": ("memory.recall", "memory.write", "personalize"),
}


def describe_travel_agents() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for slug, agent in REGISTRY.items():
        caps = tuple(agent.capabilities) or _TRAVEL_CAPS.get(slug, ())
        out.append(
            {
                "id": slug,
                "name": agent.name,
                "role": agent.role,
                "domain": getattr(agent, "domain", "travel"),
                "capabilities": list(caps),
                "kind": "travel",
            }
        )
    return out


def catalog() -> dict[str, Any]:
    """The full manifest: agents, grouped by domain and indexed by capability."""
    agents = [*describe_travel_agents(), *describe_task_agents()]

    domains: dict[str, list[str]] = {}
    capabilities: dict[str, list[str]] = {}
    for agent in agents:
        domains.setdefault(agent["domain"], []).append(agent["id"])
        for cap in agent["capabilities"]:
            capabilities.setdefault(cap, []).append(agent["id"])

    return {
        "count": len(agents),
        "domains": {name: sorted(ids) for name, ids in sorted(domains.items())},
        "capabilities": dict(sorted(capabilities.items())),
        "agents": agents,
    }


def resolve_by_capability(capability: str) -> list[str]:
    """Every agent id that advertises `capability`. The routing primitive."""
    return catalog()["capabilities"].get(capability, [])
