"""Agent registry — the plug-in point for the "extensible ecosystem" (spec §4).

All 20 agents are registered here. Adding a new agent: create the module,
subclass BaseAgent, import it, and add it to REGISTRY.

Tier 1 (core intelligence — 8 parallel): flight, hotel, research, weather_risk,
    visa, emergency, crowd, risk_advisory
Tier 2 (enrichment — 9 parallel after critic): concierge, transport, sustainability,
    payment, insurance, recommendation, analytics, language, shopping
Tier 3 (assembly — 3 sequential): budget, itinerary, memory
"""

from app.agents.base import BaseAgent
from app.agents.analytics import AnalyticsAgent
from app.agents.budget import BudgetAgent
from app.agents.chief import ChiefAgent
from app.agents.concierge import ConciergeAgent
from app.agents.crowd import CrowdAgent
from app.agents.emergency import EmergencyAgent
from app.agents.flight import FlightAgent
from app.agents.hotel import HotelAgent
from app.agents.insurance import InsuranceAgent
from app.agents.itinerary import ItineraryAgent
from app.agents.language import LanguageAgent
from app.agents.memory import MemoryAgent
from app.agents.payment import PaymentAgent
from app.agents.recommendation import RecommendationAgent
from app.agents.research import ResearchAgent
from app.agents.risk_advisory import RiskAdvisoryAgent
from app.agents.shopping import ShoppingAgent
from app.agents.sustainability import SustainabilityAgent
from app.agents.transport import TransportAgent
from app.agents.visa import VisaAgent
from app.agents.weather_risk import WeatherRiskAgent

#: All 20 agents — the full vision roster (spec §4).
REGISTRY: dict[str, BaseAgent] = {
    agent.slug: agent
    for agent in (
        # Chief orchestrator
        ChiefAgent(),
        # Tier 1 — core intelligence (8 parallel)
        FlightAgent(),
        HotelAgent(),
        ResearchAgent(),
        WeatherRiskAgent(),
        VisaAgent(),
        EmergencyAgent(),
        CrowdAgent(),
        RiskAdvisoryAgent(),
        # Tier 2 — enrichment (9 parallel, after critic)
        ConciergeAgent(),
        TransportAgent(),
        SustainabilityAgent(),
        PaymentAgent(),
        InsuranceAgent(),
        RecommendationAgent(),
        AnalyticsAgent(),
        LanguageAgent(),
        ShoppingAgent(),
        # Tier 3 — assembly (3 sequential)
        BudgetAgent(),
        ItineraryAgent(),
        MemoryAgent(),
    )
}

__all__ = [
    "REGISTRY",
    "BaseAgent",
]
