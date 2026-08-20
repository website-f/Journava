"""Recommendation Agent — personalized activity recommendations based on traveler profile.

Beyond suggesting things to do, this agent *mixes with the Research agent*: when the
traveller needs halal, every food pick's label is re-derived from the shared halal
tooling (JAKIM / HalalTrip + a live Camofox crawl) rather than trusted from the LLM.
That both enriches the picks and makes a bad 'halal_confidence' impossible to ship.
"""

from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import (
    AgentResult,
    Option,
    TravelerProfile,
    TripRequest,
    coerce_halal_confidence,
)
from app.core import llm
from app.tools import halal

logger = logging.getLogger(__name__)

#: Categories (or name/why keywords) that mark a pick as food — the only kind we
#: attach a halal label to.
_FOOD_CATEGORIES = {"food", "dining", "restaurant", "culinary", "street_food", "cafe", "market"}
_FOOD_KEYWORDS = ("restaurant", "food", "dining", "eatery", "street food", "cafe", "market", "kitchen")

SYSTEM = """You are Journava's Recommendation engine. You suggest personalised, \
specific things to do at a destination, tuned to ONE traveller's profile.

Return STRICT JSON only (no prose):
{
  "activities": [
    {
      "name": "A specific place or experience (never a generic category)",
      "category": "food | culture | nature | adventure | nightlife | shopping | wellness | family",
      "why": "One sentence: why THIS traveller, given their interests/pace/budget",
      "area": "Neighbourhood / district, if known",
      "best_time": "e.g. 'early morning', 'sunset', 'weekday'",
      "duration_hr": 2,
      "cost_usd": 20,
      "booking_hint": "How to book, or 'walk-in' / 'free'",
      "halal_confidence": "certified | muslim_friendly | unverified | null"
    }
  ]
}

Rules:
- Return 7 VARIED activities spanning DIFFERENT categories (do not return 7 restaurants).
- Respect the traveller's dislikes and allergies; lean into their stated interests and pace.
- halal_confidence: set it ONLY for food/dining picks, and use EXACTLY one of
  'certified' | 'muslim_friendly' | 'unverified' — never 'high'/'medium'/'low'/'yes'.
  Use null for non-food activities. Do NOT claim 'certified' unless a certification
  body clearly lists it; when unsure use 'unverified' (Journava re-checks every label).
"""

USER = (
    "Destination: {destination}\n"
    "Interests: {interests}\n"
    "Pace: {pace}\n"
    "Budget: {budget}\n"
    "Companions: {companions}\n"
    "Halal required: {halal}\n"
    "Cuisine likes: {likes}\n"
    "Cuisine dislikes: {dislikes}\n"
    "Allergies: {allergies}\n"
    "Suggest activities strictly following the schema."
)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _is_food(activity: dict[str, Any]) -> bool:
    cat = str(activity.get("category", "")).strip().lower().replace("-", "_").replace(" ", "_")
    if cat in _FOOD_CATEGORIES:
        return True
    blob = f"{activity.get('name', '')} {activity.get('why', '')}".lower()
    return any(kw in blob for kw in _FOOD_KEYWORDS)


class RecommendationAgent(BaseAgent):
    slug = "recommendation"
    name = "Recommendation"
    role = "Personalized picks · based on profile"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"
        interests = ", ".join(profile.interests) if profile.interests else "culture, food"
        budget = (
            f"{request.budget_amount} {request.budget_currency}"
            if request.budget_amount is not None
            else f"flexible ({profile.budget_currency})"
        )

        try:
            resp = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": USER.format(
                            destination=destination,
                            interests=interests,
                            pace=profile.pace,
                            budget=budget,
                            companions=profile.companions,
                            halal=profile.halal_required,
                            likes=", ".join(profile.cuisine_likes) or "—",
                            dislikes=", ".join(profile.cuisine_dislikes) or "—",
                            allergies=", ".join(profile.allergies) or "—",
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="recommendation",
            )
            data = json.loads(resp)
        except Exception:  # noqa: BLE001 — degrade to an empty result, never crash the plan
            data = {"activities": []}

        activities: list[dict[str, Any]] = [
            a for a in (data.get("activities") or []) if isinstance(a, dict)
        ]
        # Normalise every halal label up front: nothing downstream can trip on a
        # stray 'high', and the raw payload we return is already clean.
        for a in activities:
            a["halal_confidence"] = coerce_halal_confidence(a.get("halal_confidence"))

        warnings: list[str] = []

        # Mix with the Research agent's halal tooling. For food picks, when the
        # traveller needs halal, re-derive the label from JAKIM / HalalTrip and a
        # live Camofox crawl instead of trusting the model's guess.
        if profile.halal_required and activities:
            food_idx = [i for i, a in enumerate(activities) if _is_food(a)]
            if food_idx:
                self.emit(
                    "working",
                    f"Verifying halal for {len(food_idx)} food pick(s) via directories + Camofox",
                )
                checks = await asyncio.gather(
                    *(
                        halal.check_certification(activities[i].get("name", ""), country=destination)
                        for i in food_idx
                    ),
                    return_exceptions=True,
                )
                corroborated = 0
                for i, check in zip(food_idx, checks, strict=True):
                    if not isinstance(check, dict):
                        continue
                    conf = check.get("confidence", "unverified")
                    activities[i]["halal_confidence"] = conf
                    activities[i]["halal_source"] = check.get("source")
                    activities[i]["halal_cert_body"] = check.get("cert_body")
                    if check.get("cert_body") or conf != "unverified":
                        corroborated += 1
                if corroborated:
                    self.emit(
                        "active",
                        f"Halal: {corroborated}/{len(food_idx)} food pick(s) corroborated",
                    )
                else:
                    warnings.append(
                        "No food pick could be confirmed halal against JAKIM/HalalTrip or a "
                        "live crawl — treat labels as unverified and confirm locally."
                    )

        options: list[Option] = []
        for i, a in enumerate(activities):
            food = _is_food(a)
            reason_bits = [str(a.get("why", "")).strip()]
            if a.get("area"):
                reason_bits.append(f"Area: {a['area']}")
            if a.get("best_time"):
                reason_bits.append(f"Best time: {a['best_time']}")
            if a.get("booking_hint"):
                reason_bits.append(f"Booking: {a['booking_hint']}")
            if food and a.get("halal_source"):
                body = a.get("halal_cert_body")
                src = f"{body}" if body else a["halal_source"]
                reason_bits.append(f"Halal: {a.get('halal_confidence')} (via {src})")

            options.append(
                Option(
                    id=f"rec-{i}",
                    kind="activity",
                    title=str(a.get("name", "")),
                    price_amount=_to_decimal(a.get("cost_usd")),
                    price_currency="USD" if a.get("cost_usd") is not None else None,
                    provider=str(a.get("category") or "Experience").replace("_", " ").title(),
                    reasoning=" · ".join(b for b in reason_bits if b),
                    halal_confidence=a.get("halal_confidence"),
                    source="llm",
                    raw={"category": a.get("category"), "duration_hr": a.get("duration_hr")},
                )
            )

        return AgentResult(
            agent=self.slug,
            summary=f"{len(options)} personalized picks for {destination}",
            options=options,
            warnings=warnings,
            data={"destination": destination, "activities": activities},
        )
