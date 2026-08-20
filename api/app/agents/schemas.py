"""Pydantic v2 contracts shared by every agent (spec §6: structured agent I/O)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# --------------------------------------------------------------------------- #
# Traveler profile & preference scoping (§7.5)
# --------------------------------------------------------------------------- #

Scope = Literal["hard_filter", "soft_ranking", "not_applicable"]
HalalConfidence = Literal["certified", "muslim_friendly", "unverified"]

#: Free-form values agents/LLMs commonly emit, mapped onto the strict enum.
_HALAL_ALIASES: dict[str, HalalConfidence] = {
    "certified": "certified",
    "halal_certified": "certified",
    "certified_halal": "certified",
    "jakim": "certified",
    "muis": "certified",
    "mui": "certified",
    "muslim_friendly": "muslim_friendly",
    "muslimfriendly": "muslim_friendly",
    "friendly": "muslim_friendly",
    "halal_friendly": "muslim_friendly",
    "halal": "muslim_friendly",
    "high": "muslim_friendly",
    "medium": "muslim_friendly",
    "moderate": "muslim_friendly",
    "likely": "muslim_friendly",
    "yes": "muslim_friendly",
    "true": "muslim_friendly",
    "unverified": "unverified",
    "unknown": "unverified",
    "unsure": "unverified",
    "low": "unverified",
    "maybe": "unverified",
    "no": "unverified",
    "false": "unverified",
}


def coerce_halal_confidence(value: Any) -> HalalConfidence | None:
    """Normalise a free-form halal signal onto the strict :data:`HalalConfidence`.

    Agents — and the LLMs behind them — routinely emit values the schema does not
    allow ('high', 'medium', 'halal certified', ``True``). That used to raise a
    ``ValidationError`` and abort the entire trip plan. We map the common ones and
    fall back to the conservative 'unverified' for anything unrecognised. Empty /
    null stays ``None`` (meaning "not assessed / not applicable"). A model's own
    confidence ('high'/'medium') is deliberately capped at 'muslim_friendly' — only
    a named certification body earns 'certified' (enforced downstream in §7.5).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "muslim_friendly" if value else "unverified"
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if not text or text in {"null", "none", "n/a", "na"}:
        return None
    return _HALAL_ALIASES.get(text, "unverified")


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

    @field_validator("halal_confidence", mode="before")
    @classmethod
    def _normalise_halal(cls, v: Any) -> Any:
        # A bad halal label must never 500 the whole plan — coerce, don't reject.
        return coerce_halal_confidence(v)


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
