"""Pydantic v2 contracts shared by every agent (spec §6: structured agent I/O)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Traveler profile & preference scoping (§7.5)
# --------------------------------------------------------------------------- #

Scope = Literal["hard_filter", "soft_ranking", "not_applicable"]
HalalConfidence = Literal["certified", "muslim_friendly", "unverified"]


class TravelerProfile(BaseModel):
    """Standing preferences. An unset field means: search globally."""

    halal_required: bool = False
    allergies: list[str] = Field(default_factory=list)
    cuisine_likes: list[str] = Field(default_factory=list)
    cuisine_dislikes: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    pace: Literal["relaxed", "balanced", "packed"] = "balanced"
    budget_currency: str = "MYR"
    home_airport: str | None = None
    max_connections: int | None = None
    avoid_red_eye: bool = False
    seat_preference: Literal["window", "aisle", "none"] | None = None
    accessibility: dict[str, Any] = Field(default_factory=dict)
    hotel_preferences: dict[str, Any] = Field(default_factory=dict)
    loyalty_programs: list[str] = Field(default_factory=list)
    companions: int = 1
    language_preferences: list[str] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Trip request / plan
# --------------------------------------------------------------------------- #


class TripRequest(BaseModel):
    """The user's goal, as parsed from the Command Center input."""

    goal: str
    origin: str | None = None
    destination: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    travellers: int = 1
    budget_amount: Decimal | None = None
    budget_currency: str = "MYR"
    pace: Literal["relaxed", "balanced", "packed"] | None = None


#: Where an option came from. Surfaced as a badge so the traveller can tell a
#: bookable API fare from something an agent read on a web page (§5).
OptionSource = Literal["atlas", "amadeus", "camofox", "llm", "mock", "research", "supplier"]


class Option(BaseModel):
    """A single ranked candidate (flight, hotel, activity…)."""

    id: str
    kind: Literal["flight", "hotel", "activity", "restaurant", "transport"]
    title: str
    price_amount: Decimal | None = None
    price_currency: str | None = None
    provider: str | None = None
    booking_url: str | None = None
    # Explainability is a product requirement, not a nice-to-have (§3.2).
    reasoning: str | None = None
    # Set only for food/activity options when the profile requires halal.
    halal_confidence: HalalConfidence | None = None
    # True when a crawled price has been reconciled against an API (§5).
    verified: bool = False
    last_checked: str | None = None
    #: Which source produced this option — drives the result badge.
    source: OptionSource | None = None
    #: For crawled options, the page the agent actually read. Always shown, so a
    #: research-derived fare can be checked by the traveller rather than trusted.
    source_url: str | None = None
    #: True when this option can be carried into a real booking flow.
    bookable: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class ItineraryItem(BaseModel):
    day_index: int
    kind: Literal["flight", "hotel", "activity", "meal", "transport"]
    title: str
    starts_at: str | None = None
    ends_at: str | None = None
    reasoning: str | None = None
    cost_amount: Decimal | None = None
    cost_currency: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """Uniform envelope every agent returns to the Chief Agent."""

    agent: str
    summary: str
    options: list[Option] = Field(default_factory=list)
    items: list[ItineraryItem] = Field(default_factory=list)
    # Populated when a preference narrowed the search (audit trail for §7.5).
    applied_preferences: dict[str, Scope] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
