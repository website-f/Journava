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
        parts.append(
            "Halal dining REQUIRED (restaurants = hard filter, flights = MOML meal code only, hotels = soft preference for halal breakfast)."
        )
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
    # Learned taste from the traveller's own history — personalises every agent.
    taste = (profile.extras or {}).get("taste") if isinstance(profile.extras, dict) else None
    if isinstance(taste, dict):
        if taste.get("loves"):
            parts.append(
                f"LEARNED TASTE (from past trips) — leans toward: {', '.join(taste['loves'])}; "
                "favour options that match this."
            )
        if taste.get("visited"):
            parts.append(f"Has already been to: {', '.join(taste['visited'])} (suggest fresh spots).")
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
        {
            "role": "user",
            "content": CHIEF_USER.format(
                goal=request.goal,
                profile=_profile_summary(profile),
            ),
        },
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
        {
            "role": "user",
            "content": FLIGHT_USER.format(
                origin=request.origin or profile.home_airport or "not specified",
                destination=request.destination or "not specified",
                depart_date=request.start_date or "flexible",
                return_date=request.end_date or "one-way or flexible",
                adults=request.travellers,
                budget=request.budget_amount or "no limit",
                currency=request.budget_currency or profile.budget_currency,
                max_connections=profile.max_connections
                if profile.max_connections is not None
                else "any",
                avoid_red_eye=profile.avoid_red_eye,
            ),
        },
    ]


# --------------------------------------------------------------------------- #
# Hotel Agent
# --------------------------------------------------------------------------- #

HOTEL_SYSTEM = """\
You are Journava's Hotel Agent. Recommend hotels for the destination and dates, \
GROUNDED in the RESEARCH provided (a live web crawl of booking sites).

Rules:
- Prefer REAL hotel names, areas and realistic nightly prices you can see in the
  research; only fall back to your own knowledge when the research is thin, and
  say so in the reasoning. Never invent a hotel the research contradicts.
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

RESEARCH (live crawl — use the real names/prices you see, cite nothing you didn't):
{research}

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
        "rating": 4.5,
        "location": "area/district",
        "amenities": ["wifi", "pool", "halal_breakfast"],
        "near_transit": true,
        "accessibility": true
      }}
    }}
  ]
}}
"""


def hotel_messages(
    request: TripRequest, profile: TravelerProfile, research: str = ""
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": HOTEL_SYSTEM},
        {
            "role": "user",
            "content": HOTEL_USER.format(
                destination=request.destination or "not specified",
                checkin=request.start_date or "flexible",
                checkout=request.end_date or "flexible",
                guests=request.travellers,
                budget=request.budget_amount or "no limit",
                currency=request.budget_currency or profile.budget_currency,
                research=research or "(no live results — use your best knowledge)",
                profile=_profile_summary(profile),
            ),
        },
    ]


# --------------------------------------------------------------------------- #
# Research Agent
# --------------------------------------------------------------------------- #

RESEARCH_SYSTEM = """\
You are Journava's Research / Travel-Intelligence Agent. Generate comprehensive
destination intelligence for a traveler planning a trip. You combine what a real\
research pipeline (YouTube sentiment, Reddit threads, official guides) would produce.

Rules:
- Lead with the MOST FAMOUS, iconic, must-see attractions the destination is
  actually known for — the places a well-travelled local or a top travel guide
  would insist a first-timer not miss (e.g. for Doha: Souq Waqif, Museum of
  Islamic Art, The Pearl / Villaggio Mall, Katara, Corniche). Rank by fame +
  traveller rating, best first. NEVER pad the list with generic filler like
  "Central Market", "Old Town Walking Tour" or "City Museum" unless that place
  is genuinely a signature landmark of THIS destination.
- Honour the traveller's own request verbatim: if they ask for a specific
  activity or vibe (camping, diving, nightlife, hiking, a night in the desert),
  those experiences MUST appear in the attractions with concrete named spots.
- Give every attraction/restaurant a "rating" from 1.0–5.0 reflecting real
  traveller sentiment (round to one decimal), so the best rise to the top.
- Be specific: name real places, restaurants, and events — not generic filler.
- If halal_required is true, ALL dining recommendations MUST be halal-certified
  or clearly Muslim-friendly with a confidence label. Never claim "certified" \
  without naming a certification body (JAKIM, MUIS, MUI). Treat your own label as
  a hypothesis — it is re-checked against the certification directories after you
  answer, and an unsupported "certified" will be downgraded.
- REAL, VERIFIABLE places only. Every name must be a place that genuinely exists
  and a traveller could find on a map or Google. Do NOT invent venues — above all
  never fabricate hyper-specific outlets like airport/mall stalls with a terminal,
  gate or food-court number ("Halal Ramen (Terminal 1, Food Court)", "Matsuri
  Curry House (Terminal 2, B-Gate)"). If you cannot name a real halal restaurant,
  recommend a real, established restaurant or a real district/market known for that
  food instead. A real but less-specific place beats a made-up precise one.
- Include safety tips, local customs, and best times to visit.
- Each attraction/restaurant needs a one-line reasoning for why it's recommended.
- Report DISAGREEMENT between sources in "contradictions_detected" rather than \
  averaging it away. "Highly rated, but recent threads complain about midday \
  queues" is more useful to a traveler than either half alone.
- Output ONLY valid JSON — no markdown.
"""

RESEARCH_USER = """\
Generate destination intelligence:
- Destination: {destination}
- Traveller's exact request: "{traveller_request}"  ← honour every specific ask in here
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
      "rating": 4.7,
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
      "rating": 4.5,
      "estimated_cost": 45.00,
      "cost_currency": "MYR"
    }}
  ],
  "safety_tips": ["tip 1", "tip 2"],
  "customs": ["custom 1", "custom 2"],
  "best_times": ["morning for X", "evening for Y"],
  "sentiment_summary": "Overall traveler sentiment in 2-3 sentences",
  "contradictions_detected": [
    {{
      "topic": "e.g. St Mark's Basilica",
      "claim": "What the popular/official view says",
      "counter_claim": "What recent traveler reports say instead",
      "sources": "which sources disagree"
    }}
  ]
}}
"""


def research_messages(
    request: TripRequest,
    profile: TravelerProfile,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": RESEARCH_SYSTEM},
        {
            "role": "user",
            "content": RESEARCH_USER.format(
                destination=request.destination or "the destination",
                traveller_request=(request.goal or "").strip()[:400] or "a great trip",
                start_date=request.start_date or "flexible",
                end_date=request.end_date or "flexible",
                interests=", ".join(profile.interests) if profile.interests else "general",
                halal_required=profile.halal_required,
                allergies=", ".join(profile.allergies) if profile.allergies else "none",
                profile=_profile_summary(profile),
            ),
        },
    ]


# --------------------------------------------------------------------------- #
# Itinerary Agent
# --------------------------------------------------------------------------- #

ITINERARY_SYSTEM = """\
You are Journava's Itinerary Agent. Assemble a day-by-day travel plan from the \
upstream results (flights, hotels, activities). You optimize for the traveler's \
pace preference and interests.

Rules:
- The trip is EXACTLY {days} days. Every item's day_index MUST be between 1 and \
  {days} inclusive, and you MUST cover all {days} days — never more, never fewer.
- Pace "relaxed" = 2 items/day, "balanced" = 3, "packed" = 5.
- Each item needs: day_index (1-based), kind, title, starts_at (HH:MM), ends_at, \
  reasoning (one sentence: "why this?"), and estimated cost.
- Interleave meals (mark halal confidence if profile requires halal). Meals MUST
  be REAL, findable restaurants — prefer names from the research list above, or a
  real, well-known eatery/district. NEVER invent fictional outlets with terminal,
  gate or food-court numbers.
- Schedule each place ONCE across the whole trip — do not repeat the same
  attraction or restaurant on more than one day.
- Place travel/transport between distant activities.
- Output ONLY valid JSON — no markdown.
"""

ITINERARY_USER = """\
Build a day-by-day itinerary:

Trip: {destination}, {start_date} to {end_date} ({days} days)
Traveller's exact request: "{traveller_request}"  ← if it names a specific experience (e.g. a night camping), schedule it on a real day with a concrete named spot
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

    def _compact(o: dict[str, Any]) -> dict[str, Any]:
        """Just what the scheduler needs from a place — not the whole payload."""
        return {
            "title": o.get("title"),
            "kind": o.get("kind"),
            "why": (o.get("reasoning") or "")[:120],
            "price": o.get("price_amount"),
            "halal": o.get("halal_confidence"),
        }

    # Summarise upstream for context injection.
    summary_parts: list[str] = []
    for agent_slug, result in upstream_results.items():
        if agent_slug in ("chief", "budget", "itinerary", "memory"):
            continue
        if not isinstance(result, dict):
            continue
        options = result.get("options", [])
        summary = result.get("summary", "")
        if agent_slug == "research" and options:
            # The day plan is BUILT from these — pass the full ranked shortlist
            # (best first, compacted), not just 3, so it schedules real places
            # instead of inventing the rest of a multi-day trip.
            shortlist = [_compact(o) for o in options[:14]]
            summary_parts.append(
                f"[research] {len(options)} ranked places (schedule from these): "
                f"{json.dumps(shortlist, default=str)}"
            )
        elif agent_slug == "crowd":
            # Crowd level + best-times drive the off-peak scheduling instruction.
            data = result.get("data") or {}
            summary_parts.append(
                f"[crowd] {summary} | {json.dumps(data, default=str)[:800]}"
            )
        elif options:
            summary_parts.append(
                f"[{agent_slug}] {len(options)} options: {json.dumps(options[:3], default=str)}"
            )
        elif summary:
            summary_parts.append(f"[{agent_slug}] {summary}")

    # Trip length: explicit dates win, else the duration parsed from the goal
    # ("3 days"), else a 7-day default — so the itinerary is never longer than
    # the traveller asked for.
    days = request.effective_days

    return [
        {"role": "system", "content": ITINERARY_SYSTEM.format(days=days)},
        {
            "role": "user",
            "content": ITINERARY_USER.format(
                destination=request.destination or "the destination",
                traveller_request=(request.goal or "").strip()[:400] or "a great trip",
                start_date=request.start_date or "Day 1",
                end_date=request.end_date or f"Day {days}",
                days=days,
                pace=pace,
                items_per_day=items_per_day,
                travellers=request.travellers,
                upstream_summary="\n".join(summary_parts) or "No upstream data available yet.",
                profile=_profile_summary(profile),
            ),
        },
    ]
