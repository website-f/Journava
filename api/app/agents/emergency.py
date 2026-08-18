"""Emergency Agent — emergency contacts, embassy info, nearest hospitals.

Uses REST Countries for base data + LLM for emergency service numbers,
embassy contacts, and crisis response procedures.
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

EMERGENCY_SYSTEM = """You are Journava's Emergency agent. Provide emergency information for a destination.
Respond in JSON:
{"police": "number", "ambulance": "number", "fire": "number",
 "embassy_phone": "+XX...", "embassy_address": "...",
 "nearest_hospital": "name and location",
 "crisis_procedures": "what to do in emergency",
 "useful_apps": ["app1", "app2"]}"""

EMERGENCY_USER = """Destination: {destination}
Country info: {country_data}
Provide emergency contacts and procedures for a Malaysian traveler."""


class EmergencyAgent(BaseAgent):
    slug = "emergency"
    name = "Emergency"
    role = "Emergency contacts · embassy · crisis procedures"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"
        country = await rest_countries.country_info(destination)

        try:
            response = await llm.complete(
                [
                    {"role": "system", "content": EMERGENCY_SYSTEM},
                    {
                        "role": "user",
                        "content": EMERGENCY_USER.format(
                            destination=destination,
                            country_data=json.dumps(country) if country else "{}",
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="emergency",
            )
            contacts = json.loads(response)
        except Exception:  # noqa: BLE001
            contacts = {
                "police": "Contact local authorities",
                "ambulance": "Contact local hospital",
                "fire": "Contact local fire department",
                "embassy_phone": "Check Malaysian embassy website",
                "embassy_address": "Search 'Malaysian embassy in " + destination + "'",
                "nearest_hospital": "Ask hotel concierge",
                "crisis_procedures": "Contact embassy immediately, keep copies of all documents.",
                "useful_apps": ["Google Maps", "XE Currency"],
            }

        return AgentResult(
            agent=self.slug,
            summary=f"Emergency contacts prepared for {destination}",
            data={
                "destination": destination,
                "emergency_numbers": {
                    "police": contacts.get("police"),
                    "ambulance": contacts.get("ambulance"),
                    "fire": contacts.get("fire"),
                },
                "embassy": {
                    "phone": contacts.get("embassy_phone"),
                    "address": contacts.get("embassy_address"),
                },
                "nearest_hospital": contacts.get("nearest_hospital"),
                "crisis_procedures": contacts.get("crisis_procedures"),
                "useful_apps": contacts.get("useful_apps", []),
            },
        )
