"""Prompt templates for the 4 core agents (Phase 1).

Each function receives a TripRequest and TravelerProfile and returns a list of
messages ready for llm.complete(). Keeping prompts here keeps the agent logic
focused on orchestration, parsing, and preference scoping.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from app.agents.schemas import TravelerProfile, TripRequest

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _profile_summary(profile: TravelerProfile) -> str:
    """One-paragraph profile summary injected into every agent's context."""
    parts: list[str] = []
    if profile.halal_required:
        parts.append("Halal dining REQUIRED (restaurants = hard filter, flights = MOML meal code only, hotels = soft preference for halal breakfast).")
    if profile.allergies:
        parts.append(f"Allergies: {', '.join(profile.allergies)}.")
    if profile.cuisine_likes:
        parts.append(f"Cuisine likes: {', '.join(profile.cuisine_likes)}.")
    if profile.cuisine_dislikes:
        parts.append(f"Cuisine dislikes: {', '.join(profile.cuisine_dislikes)}.")
    if profile.interests:
        parts.append(f"Interests: {', '.join(profile.interests)}.")
    if profile.avoid_red_eye:
        parts.append("Avoids red-eye flights (soft ranking, never a hard filter).")
    if profile.max_connections is not None:
        parts.append(f"Max connections: {profile.max_connections}.")
    if profile.home_airport:
        parts.append(f"Home airport: {profile.home_airport}.")
    if profile.accessibility:
        parts.append(f"Accessibility needs: {json.dumps(profile.accessibility)}.")
    if profile.seat_preference:
        parts.append(f"Seat preference: {profile.seat_preference}.")
    parts.append(f"Default pace: {profile.pace}. Budget currency: {profile.budget_currency}.")
    return " ".join(parts) if parts else "No standing preferences — search globally."


def _today() -> str:
    return date.today().isoformat()


# --------------------------------------------------------------------------- #
# Chief Agent
# --------------------------------------------------------------------------- #

CHIEF_SYSTEM = """\
You are Journava's Chief Agent — the orchestration brain of an autonomous \
multi-agent travel platform. Your job is to parse a free-form trip goal into \
structured fields that downstream specialists need.

Rules:
- If the user doesn't specify a field, leave it null — the specialist searches globally.
- Dates should be ISO 8601 (YYYY-MM-DD). If the user says "next month" or \
  "7 days in December", infer reasonable dates relative to today ({today}).
- Budget should be a number + currency code. Default currency: MYR.
- Output ONLY valid JSON — no markdown, no explanation.
"""

CHIEF_USER = """\
Parse this trip goal into structured fields:

\"\"\"{goal}\"\"\"

Traveler context: {profile}

Return JSON with these keys (null for unknown):
{{
  "origin": string | null,
  "destination": string | null,
  "start_date": "YYYY-MM-DD" | null,
  "end_date": "YYYY-MM-DD" | null,
  "travellers": int | null,
  "budget_amount": number | null,
  "budget_currency": string | null,
  "interests_detected": [string] | null
}}
"""


def chief_messages(request: TripRequest, profile: TravelerProfile) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": CHIEF_SYSTEM.format(today=_today())},
        {"role": "user", "content": CHIEF_USER.format(
            goal=request.goal,
            profile=_profile_summary(profile),
        )},
    ]


# --------------------------------------------------------------------------- #
# Flight Agent
# --------------------------------------------------------------------------- #

FLIGHT_SYSTEM = """\
You are Journava's Flight Agent. Generate realistic flight options based on the \
search parameters. You simulate what a real flight search API would return.

Rules:
- Flights are ALWAYS from the global inventory — never filter by dietary preference.
- Halal preference only adds a meal code (MOML) to the booking, never removes options.
- Return 4-5 options ranked into buckets: cheapest, cheapest_with_baggage, best_value, best_time.
- Each option must include: airline, flight_number, departure_time, arrival_time, \
  stops, duration_hours, price, currency, baggage_included (bool), and a one-sentence reasoning.
- Output ONLY valid JSON — no markdown.
"""

FLIGHT_USER = """\
Search flights:
- From: {origin}
- To: {destination}
- Depart: {depart_date}
- Return: {return_date}
- Adults: {adults}
- Budget preference: {budget} {currency}
- Max connections preferred: {max_connections}
- Avoid red-eye: {avoid_red_eye}

Return a JSON object:
{{
  "options": [
    {{
      "id": "FL001",
      "title": "Airline — Flight Number",
      "price_amount": 1200.00,
      "price_currency": "MYR",
      "provider": "Airline Name",
      "reasoning": "Why this option ranks here",
      "raw": {{
        "airline": "...",
        "flight_number": "...",
        "departure_time": "HH:MM",
        "arrival_time": "HH:MM",
        "stops": 0,
        "duration_hours": 5.5,
        "baggage_included": true,
        "bucket": "cheapest | cheapest_with_baggage | best_value | best_time"
      }}
    }}
  ]
}}
"""


def flight_messages(request: TripRequest, profile: TravelerProfile) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": FLIGHT_SYSTEM},
        {"role": "user", "content": FLIGHT_USER.format(
            origin=request.origin or profile.home_airport or "not specified",
            destination=request.destination or "not specified",
            depart_date=request.start_date or "flexible",
            return_date=request.end_date or "one-way or flexible",
            adults=request.travellers,
            budget=request.budget_amount or "no limit",
            currency=request.budget_currency or profile.budget_currency,
            max_connections=profile.max_connections if profile.max_connections is not None else "any",
            avoid_red_eye=profile.avoid_red_eye,
        )},
    ]


# --------------------------------------------------------------------------- #
# Hotel Agent
# --------------------------------------------------------------------------- #

HOTEL_SYSTEM = """\
You are Journava's Hotel Agent. Generate realistic hotel options for the \
destination and dates. Consider the traveler's preferences for ranking.

Rules:
- Halal preference = soft signal for hotels (halal breakfast option); never a hard filter on accommodation.
- Accessibility = hard filter — if the traveler has accessibility needs, ONLY return accessible rooms.
- Return 4-5 options with a one-sentence reasoning for each explaining "Why this hotel?"
- Output ONLY valid JSON — no markdown.
"""

HOTEL_USER = """\
Search hotels:
- Destination: {destination}
- Check-in: {checkin}
- Check-out: {checkout}
- Guests: {guests}
- Budget preference: {budget} {currency}
- Traveler profile: {profile}

Return a JSON object:
{{
  "options": [
    {{
      "id": "HT001",
      "title": "Hotel Name",
      "price_amount": 350.00,
      "price_currency": "MYR",
      "provider": "Booking source",
      "reasoning": "Why Journava chose this",
      "raw": {{
        "stars": 4,
        "location": "area/district",
        "amenities": ["wifi", "pool", "halal_breakfast"],
        "near_transit": true,
        "accessibility": true
      }}
    }}
  ]
}}
"""


def hotel_messages(request: TripRequest, profile: TravelerProfile) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": HOTEL_SYSTEM},
        {"role": "user", "content": HOTEL_USER.format(
            destination=request.destination or "not specified",
            checkin=request.start_date or "flexible",
            checkout=request.end_date or "flexible",
            guests=request.travellers,
            budget=request.budget_amount or "no limit",
            currency=request.budget_currency or profile.budget_currency,
            profile=_profile_summary(profile),
        )},
    ]


# --------------------------------------------------------------------------- #
# Research Agent
# --------------------------------------------------------------------------- #

RESEARCH_SYSTEM = """\
You are Journava's Research / Travel-Intelligence Agent. Generate comprehensive
destination intelligence for a traveler planning a trip. You combine what a real\
research pipeline (YouTube sentiment, Reddit threads, official guides) would produce.

Rules:
- Be specific: name real places, restaurants, and events — not generic filler.
- If halal_required is true, ALL dining recommendations MUST be halal-certified
  or clearly Muslim-friendly with a confidence label. Never claim "certified" \
  without naming a certification body (JAKIM, MUIS, MUI).
- Include safety tips, local customs, and best times to visit.
- Each attraction/restaurant needs a one-line reasoning for why it's recommended.
- Output ONLY valid JSON — no markdown.
"""

RESEARCH_USER = """\
Generate destination intelligence:
- Destination: {destination}
- Trip dates: {start_date} to {end_date}
- Traveller interests: {interests}
- Halal required: {halal_required}
- Allergies to avoid: {allergies}
- Traveller profile: {profile}

Return a JSON object:
{{
  "attractions": [
    {{
      "title": "Place Name",
      "kind": "landmark | museum | park | market | temple | beach",
      "reasoning": "Why this is worth visiting",
      "estimated_cost": 25.00,
      "cost_currency": "MYR"
    }}
  ],
  "dining": [
    {{
      "title": "Restaurant Name",
      "cuisine": "Italian / Japanese / Local…",
      "halal_confidence": "certified | muslim_friendly | unverified",
      "reasoning": "Why this restaurant fits the traveler",
      "estimated_cost": 45.00,
      "cost_currency": "MYR"
    }}
  ],
  "safety_tips": ["tip 1", "tip 2"],
  "customs": ["custom 1", "custom 2"],
  "best_times": ["morning for X", "evening for Y"],
  "sentiment_summary": "Overall traveler sentiment in 2-3 sentences"
}}
"""


def research_messages(
    request: TripRequest,
    profile: TravelerProfile,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": RESEARCH_SYSTEM},
        {"role": "user", "content": RESEARCH_USER.format(
            destination=request.destination or "the destination",
            start_date=request.start_date or "flexible",
            end_date=request.end_date or "flexible",
            interests=", ".join(profile.interests) if profile.interests else "general",
            halal_required=profile.halal_required,
            allergies=", ".join(profile.allergies) if profile.allergies else "none",
            profile=_profile_summary(profile),
        )},
    ]


# --------------------------------------------------------------------------- #
# Itinerary Agent
# --------------------------------------------------------------------------- #

ITINERARY_SYSTEM = """\
You are Journava's Itinerary Agent. Assemble a day-by-day travel plan from the \
upstream results (flights, hotels, activities). You optimize for the traveler's \
pace preference and interests.

Rules:
- Pace "relaxed" = 2 items/day, "balanced" = 3, "packed" = 5.
- Each item needs: day_index (1-based), kind, title, starts_at (HH:MM), ends_at, \
  reasoning (one sentence: "why this?"), and estimated cost.
- Interleave meals (mark halal confidence if profile requires halal).
- Place travel/transport between distant activities.
- Output ONLY valid JSON — no markdown.
"""

ITINERARY_USER = """\
Build a day-by-day itinerary:

Trip: {destination}, {start_date} to {end_date} ({days} days)
Pace: {pace} ({items_per_day} items/day target)
Travellers: {travellers}

Available options from upstream agents:
{upstream_summary}

Traveler preferences: {profile}

Return a JSON object:
{{
  "items": [
    {{
      "day_index": 1,
      "kind": "flight | hotel | activity | meal | transport",
      "title": "Activity or event name",
      "starts_at": "09:00",
      "ends_at": "10:30",
      "reasoning": "Why this is here",
      "cost_amount": 50.00,
      "cost_currency": "MYR"
    }}
  ]
}}
"""


def itinerary_messages(
    request: TripRequest,
    profile: TravelerProfile,
    upstream_results: dict[str, Any],
) -> list[dict[str, str]]:
    pace = request.pace or profile.pace
    items_per_day = {"relaxed": 2, "balanced": 3, "packed": 5}.get(pace, 3)

    # Summarise upstream for context injection
    summary_parts: list[str] = []
    for agent_slug, result in upstream_results.items():
        if agent_slug in ("chief", "budget", "itinerary", "memory"):
            continue
        if isinstance(result, dict):
            options = result.get("options", [])
            summary = result.get("summary", "")
            if options:
                summary_parts.append(f"[{agent_slug}] {len(options)} options: {json.dumps(options[:3], default=str)}")
            elif summary:
                summary_parts.append(f"[{agent_slug}] {summary}")

    # Calculate days
    days = 7
    if request.start_date and request.end_date:
        days = max(1, (request.end_date - request.start_date).days + 1)

    return [
        {"role": "system", "content": ITINERARY_SYSTEM},
        {"role": "user", "content": ITINERARY_USER.format(
            destination=request.destination or "the destination",
            start_date=request.start_date or "Day 1",
            end_date=request.end_date or f"Day {days}",
            days=days,
            pace=pace,
            items_per_day=items_per_day,
            travellers=request.travellers,
            upstream_summary="\n".join(summary_parts) or "No upstream data available yet.",
            profile=_profile_summary(profile),
        )},
    ]
