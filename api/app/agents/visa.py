"""Visa Agent — entry requirements, documents needed, processing time.

Uses REST Countries for base country data + LLM for detailed visa requirements
based on the traveler's nationality (assumed Malaysian if not specified).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm
from app.tools import rest_countries

logger = logging.getLogger(__name__)

VISA_SYSTEM = """You are Journava's Visa agent. Determine visa requirements for a traveler.
Respond in JSON:
{"visa_required": true|false, "visa_type": "visa-free|e-visa|visa-on-arrival|embassy-visa",
 "documents": ["doc1", "doc2"], "processing_time": "X days", "cost_usd": 0,
 "notes": "important notes", "max_stay_days": 30}"""

VISA_USER = """Destination: {destination}
Country data: {country_data}
Traveler nationality: Malaysian (default)
Trip duration: {duration} days

Determine visa requirements."""


class VisaAgent(BaseAgent):
    slug = "visa"
    name = "Visa"
    role = "Entry requirements · documents · processing time"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"
        country = await rest_countries.country_info(destination)

        # Calculate trip duration
        duration = 7  # default
        if request.start_date and request.end_date:
            duration = (request.end_date - request.start_date).days

        try:
            response = await llm.complete(
                [
                    {"role": "system", "content": VISA_SYSTEM},
                    {
                        "role": "user",
                        "content": VISA_USER.format(
                            destination=destination,
                            country_data=json.dumps(country) if country else "{}",
                            duration=duration,
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="visa",
            )
            visa_info = json.loads(response)
        except Exception:  # noqa: BLE001
            visa_info = {
                "visa_required": None,
                "visa_type": "unknown",
                "documents": ["Passport (6+ months validity)"],
                "processing_time": "Check embassy",
                "cost_usd": 0,
                "notes": "Verify requirements with official sources before travel.",
                "max_stay_days": 30,
            }

        warnings = []
        if visa_info.get("visa_required") is True and visa_info.get("visa_type") == "embassy-visa":
            warnings.append("Embassy visa required — apply at least 2 weeks before departure.")

        return AgentResult(
            agent=self.slug,
            summary=f"Visa: {visa_info.get('visa_type', 'unknown')} for {destination}",
            warnings=warnings,
            data={
                "destination": destination,
                "visa_required": visa_info.get("visa_required"),
                "visa_type": visa_info.get("visa_type"),
                "documents": visa_info.get("documents", []),
                "processing_time": visa_info.get("processing_time"),
                "cost_usd": visa_info.get("cost_usd", 0),
                "max_stay_days": visa_info.get("max_stay_days", 30),
                "notes": visa_info.get("notes", ""),
                "country_currencies": country.get("currencies", []) if country else [],
                "country_languages": country.get("languages", []) if country else [],
            },
        )
