"""Language Agent — key phrases, cultural etiquette, translation tips."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm
from app.tools import rest_countries

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Language agent. Provide essential phrases and cultural tips.
Respond in JSON:
{"languages": ["language1"], "essential_phrases": [{"english": "hello", "local": "...", "pronunciation": "..."}],
 "cultural_etiquette": ["tip1", "tip2"], "dress_code": "modest|casual|formal",
 "taboo_topics": ["topic1"]}"""

USER = "Destination: {destination}\nLanguages spoken: {languages}\nProvide essential phrases and etiquette."


class LanguageAgent(BaseAgent):
    slug = "language"
    name = "Language"
    role = "Key phrases · cultural etiquette · customs"

    async def run(self, request: TripRequest, profile: TravelerProfile, *, context: dict[str, Any] | None = None) -> AgentResult:
        destination = request.destination or "unknown"
        country = await rest_countries.country_info(destination)
        languages = ", ".join(country.get("languages", [])) if country else "unknown"

        try:
            resp = await llm.complete(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER.format(destination=destination, languages=languages)}],
                response_format={"type": "json_object"}, agent="language",
            )
            data = json.loads(resp)
        except Exception:  # noqa: BLE001
            data = {"languages": [languages], "essential_phrases": [], "cultural_etiquette": ["Be respectful of local customs"], "dress_code": "casual"}

        return AgentResult(agent=self.slug, summary=f"Language guide for {destination} ({languages})", data={"destination": destination, **data})
