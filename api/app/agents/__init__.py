"""Agent registry — the plug-in point for the "extensible ecosystem" (spec §4).

Adding an agent: create the module, subclass BaseAgent, register it in REGISTRY.
The vision layer (Visa, Transport, Emergency, Concierge, Insurance, Payment,
Sustainability, Crowd, Recommendation, Analytics, Language, Shopping) plugs in
here without touching the orchestrator.
"""

from app.agents.base import BaseAgent
from app.agents.budget import BudgetAgent
from app.agents.chief import ChiefAgent
from app.agents.flight import FlightAgent
from app.agents.hotel import HotelAgent
from app.agents.itinerary import ItineraryAgent
from app.agents.memory import MemoryAgent
from app.agents.research import ResearchAgent
from app.agents.weather_risk import WeatherRiskAgent

#: The 8 agents shipped for the MVP.
REGISTRY: dict[str, BaseAgent] = {
    agent.slug: agent
    for agent in (
        ChiefAgent(),
        FlightAgent(),
        HotelAgent(),
        ResearchAgent(),
        WeatherRiskAgent(),
        BudgetAgent(),
        ItineraryAgent(),
        MemoryAgent(),
    )
}

__all__ = [
    "REGISTRY",
    "BaseAgent",
    "BudgetAgent",
    "ChiefAgent",
    "FlightAgent",
    "HotelAgent",
    "ItineraryAgent",
    "MemoryAgent",
    "ResearchAgent",
    "WeatherRiskAgent",
]
