"""Planning scopes — run only the agents a question actually needs.

The problem this solves: *"get me cheap flights from KLIA to BKI on 6 November
night"* used to wake all 21 agents. The traveller got visa requirements, embassy
phone numbers, shopping tips, carbon estimates and a language guide alongside
three flights. The answer was buried, the run took ~90s, and it burned 21 LLM
calls to answer one question.

A scope is a named subset of the graph. Each Command Center preset maps to one,
so the work matches the ask:

    flights_only   → chief · flight                         (2 agents,  ~8s)
    food           → chief · research                       (2 agents)
    hotels         → chief · hotel                          (2 agents)
    full_trip      → everything                             (21 agents, ~90s)

Rules a scope must respect:

- **Chief always runs.** It is what turns free-form text into structured fields;
  without it every specialist plans for `destination=None`.
- **Tier 3 members are pulled in on demand.** Asking for a budget implies the
  itinerary that budget aggregates, so dependencies are resolved rather than
  trusted to the caller.
- **The Critic only earns its place when there is something to critique.** A
  two-agent scope skips it; scoring one flight search against itself is a wasted
  LLM call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Agents whose results other agents consume, and what they need.
_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    # Budget sums the cheapest flight, the hotel, and the itinerary's activities.
    "budget": ("itinerary",),
    # Insurance reads the risk assessment to size the cover.
    "insurance": ("risk_advisory",),
}

#: Agents that must run last, in this order, when present in a scope.
TIER3_ORDER: tuple[str, ...] = ("itinerary", "budget", "memory")


@dataclass(frozen=True)
class Scope:
    """One planning scope: which agents, and how to present the result."""

    slug: str
    label: str
    description: str
    #: Agents to run, excluding `chief` (always included) and dependencies.
    agents: tuple[str, ...]
    #: Short imperative shown on the preset card.
    cta: str
    icon: str
    #: Example prompt seeded into the scoped Command Center input.
    placeholder: str
    #: Which result panels the frontend should render, in order.
    panels: tuple[str, ...] = ()
    #: Run the Critic + Reflexion loop for this scope.
    use_critic: bool = False
    #: Ask the Chief to write an itinerary automatically.
    auto_itinerary: bool = False
    #: Rough wall-clock estimate in seconds, for the progress ETA.
    estimate_seconds: int = 20
    #: Fields the UI should collect up front for this scope.
    inputs: tuple[str, ...] = ("goal",)
    extras: dict[str, Any] = field(default_factory=dict)

    def resolved_agents(self) -> tuple[str, ...]:
        """The full agent list, with chief first and dependencies pulled in."""
        selected: list[str] = []

        def add(slug: str) -> None:
            for dependency in _DEPENDENCIES.get(slug, ()):
                add(dependency)
            if slug not in selected:
                selected.append(slug)

        for slug in self.agents:
            add(slug)

        # `memory` closes every run: it is what makes the next one smarter.
        if "memory" not in selected:
            selected.append("memory")

        tier3 = [s for s in TIER3_ORDER if s in selected]
        parallel = [s for s in selected if s not in TIER3_ORDER]
        return ("chief", *parallel, *tier3)

    def parallel_agents(self) -> tuple[str, ...]:
        return tuple(s for s in self.resolved_agents() if s not in ("chief", *TIER3_ORDER))

    def sequential_agents(self) -> tuple[str, ...]:
        resolved = self.resolved_agents()
        return tuple(s for s in TIER3_ORDER if s in resolved)

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "label": self.label,
            "description": self.description,
            "cta": self.cta,
            "icon": self.icon,
            "placeholder": self.placeholder,
            "panels": list(self.panels),
            "agents": list(self.resolved_agents()),
            "agent_count": len(self.resolved_agents()),
            "use_critic": self.use_critic,
            "auto_itinerary": self.auto_itinerary,
            "estimate_seconds": self.estimate_seconds,
            "inputs": list(self.inputs),
            "extras": self.extras,
        }


SCOPES: dict[str, Scope] = {
    scope.slug: scope
    for scope in (
        Scope(
            slug="full_trip",
            label="Plan the whole trip",
            description=(
                "Every agent: flights, stays, food, activities, weather, risk, visa, "
                "transport and budget — assembled into a day-by-day itinerary."
            ),
            cta="Plan everything",
            icon="sparkles",
            placeholder=(
                "7-day Venice trip for 2 in September, budget RM8,000, we love food "
                "and culture, avoid crowds, max 1 connection."
            ),
            agents=(
                "flight",
                "hotel",
                "research",
                "weather_risk",
                "visa",
                "emergency",
                "crowd",
                "risk_advisory",
                "concierge",
                "transport",
                "sustainability",
                "payment",
                "insurance",
                "recommendation",
                "analytics",
                "language",
                "shopping",
                "itinerary",
                "budget",
            ),
            panels=(
                "summary",
                "flights",
                "hotels",
                "itinerary",
                "budget",
                "weather",
                "risk",
                "research",
                "practical",
            ),
            use_critic=True,
            auto_itinerary=True,
            estimate_seconds=95,
            inputs=("goal", "dates", "travellers", "budget", "pace"),
        ),
        Scope(
            slug="flights_only",
            label="Flights only",
            description=(
                "Search live inventory from Atlas and cross-check it with public "
                "research. Ranked, with a booking path."
            ),
            cta="Find flights",
            icon="plane",
            placeholder="Cheap flights from KLIA to BKI on 6 November, evening departure.",
            agents=("flight",),
            panels=("summary", "flights"),
            estimate_seconds=15,
            inputs=("goal", "dates", "travellers", "budget"),
        ),
        Scope(
            slug="food",
            label="Food near me",
            description=(
                "Restaurants and street food, halal-verified against the "
                "certification directories when your profile requires it."
            ),
            cta="Find food",
            icon="utensils",
            placeholder="Best halal food around Kota Kinabalu waterfront, budget RM50 a head.",
            agents=("research",),
            panels=("summary", "dining", "social"),
            estimate_seconds=25,
            inputs=("goal", "budget"),
            extras={"research_focus": "dining"},
        ),
        Scope(
            slug="hotels",
            label="Hotels nearby",
            description="Places to stay, compared on price, location and transit access.",
            cta="Find stays",
            icon="building",
            placeholder="Hotel in Kota Kinabalu near the airport for 3 nights under RM250/night.",
            agents=("hotel",),
            panels=("summary", "hotels"),
            estimate_seconds=18,
            inputs=("goal", "dates", "travellers", "budget"),
        ),
        Scope(
            slug="activities",
            label="Things to do",
            description="Attractions and experiences, ranked against your interests.",
            cta="Find things to do",
            icon="compass",
            placeholder="Two days of island hopping and nature around Kota Kinabalu.",
            agents=("research", "recommendation", "crowd"),
            panels=("summary", "activities", "social", "crowd"),
            estimate_seconds=35,
            inputs=("goal", "dates", "budget"),
            extras={"research_focus": "attractions"},
        ),
        Scope(
            slug="weather_risk",
            label="Weather & safety",
            description="Forecast, plus live event and threat scanning for the destination.",
            cta="Check conditions",
            icon="cloud",
            placeholder="Weather and safety for Kota Kinabalu in early November.",
            agents=("weather_risk", "risk_advisory"),
            panels=("summary", "weather", "risk"),
            estimate_seconds=25,
            inputs=("goal", "dates"),
        ),
        Scope(
            slug="entry",
            label="Visa & entry",
            description="Entry requirements, documents, processing time and emergency contacts.",
            cta="Check entry rules",
            icon="passport",
            placeholder="Do I need a visa for Japan on a Malaysian passport in December?",
            agents=("visa", "emergency", "language"),
            panels=("summary", "visa", "practical"),
            estimate_seconds=25,
            inputs=("goal", "dates"),
        ),
        Scope(
            slug="getting_around",
            label="Getting around",
            description="Airport transfers, inter-city routes and local transit.",
            cta="Plan transport",
            icon="bus",
            placeholder="How do I get from BKI airport to the city and around for 3 days?",
            agents=("transport",),
            panels=("summary", "transport"),
            estimate_seconds=15,
            inputs=("goal", "dates"),
        ),
        Scope(
            slug="budget_check",
            label="Budget check",
            description=(
                "What the trip costs, in your currency, with an itinerary to price it against."
            ),
            cta="Estimate cost",
            icon="wallet",
            placeholder="What would 5 days in Kota Kinabalu for 2 cost me, roughly?",
            agents=("flight", "hotel", "research", "itinerary", "budget", "payment"),
            panels=("summary", "budget", "itinerary"),
            estimate_seconds=55,
            inputs=("goal", "dates", "travellers", "budget"),
        ),
        Scope(
            slug="itinerary_only",
            label="Build an itinerary",
            description=(
                "Turn a destination into a day-by-day plan, paced the way you like, "
                "using research and weather."
            ),
            cta="Build itinerary",
            icon="calendar",
            placeholder="Build me a relaxed 4-day Kota Kinabalu itinerary with food and islands.",
            agents=("research", "weather_risk", "itinerary"),
            panels=("summary", "itinerary", "weather"),
            auto_itinerary=True,
            estimate_seconds=45,
            inputs=("goal", "dates", "pace", "budget"),
        ),
    )
}

DEFAULT_SCOPE = "full_trip"


def get(slug: str | None) -> Scope:
    """Resolve a scope slug, falling back to the full trip."""
    if not slug:
        return SCOPES[DEFAULT_SCOPE]
    return SCOPES.get(slug, SCOPES[DEFAULT_SCOPE])


def catalogue() -> list[dict[str, Any]]:
    """Every scope, for the Command Center home screen."""
    return [scope.as_dict() for scope in SCOPES.values()]
