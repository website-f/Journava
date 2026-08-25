"""Language Agent — key phrases, cultural etiquette, translation tips.

Research-backed: languages from REST Countries plus a Camofox crawl of etiquette /
customs with cited sources.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm
from app.tools import discover, rest_countries

logger = logging.getLogger(__name__)

SYSTEM = """You are Journava's Language agent. Provide essential phrases and \
cultural tips, grounded in the RESEARCH provided.

Give 10–12 genuinely useful essential_phrases in the local language, covering:
greetings (hello, good morning), please, thank you, yes, no, excuse me/sorry,
"how much is this?", "where is …?", "help!", "the bill please", and a
food/dietary phrase (e.g. "is this halal?" when relevant). Real local script +
a plain-English pronunciation for each.

Respond in JSON:
{"languages": ["language1"],
 "essential_phrases": [{"english": "hello", "local": "…", "pronunciation": "…"}],
 "cultural_etiquette": ["tip1", "tip2"], "dress_code": "modest|casual|formal",
 "taboo_topics": ["topic1"]}"""

USER = (
    "Destination: {destination}\nLanguages spoken: {languages}\n\n"
    "RESEARCH (live web crawl — etiquette/customs):\n{research}\n\n"
    "Provide essential phrases and etiquette."
)


class LanguageAgent(BaseAgent):
    slug = "language"
    name = "Language"
    role = "Key phrases · cultural etiquette · customs"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"

        self.emit("working", f"Researching etiquette in {destination}")
        country, research = await asyncio.gather(
            rest_countries.country_info(destination),
            discover.crawl_sources(
                [
                    f"{destination} cultural etiquette customs for tourists dos and donts",
                    f"{destination} useful phrases dress code taboo topics",
                ]
            ),
        )
        # REST Countries resolves a *country* name; a city (e.g. "Chengdu")
        # returns nothing, so don't force "unknown" — let the LLM name the local
        # language from the destination itself.
        known_langs = ", ".join(country.get("languages", [])) if country else ""
        prompt_langs = known_langs or "(determine the local language(s) from the destination)"

        try:
            resp = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": USER.format(
                            destination=destination,
                            languages=prompt_langs,
                            research=research["text"] or "(no live results — use best knowledge)",
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="language",
            )
            data = json.loads(resp)
            if not isinstance(data, dict):
                raise TypeError("LLM did not return a JSON object")
        except Exception:  # noqa: BLE001
            data = {
                "languages": [known_langs] if known_langs else [],
                "essential_phrases": [],
                "cultural_etiquette": ["Be respectful of local customs"],
                "dress_code": "casual",
            }

        # Prefer the LLM's languages (accurate for cities) over the country lookup.
        resolved = data.get("languages") or ([known_langs] if known_langs else [])
        lang_label = ", ".join(str(item) for item in resolved if item) or "local language"

        sources = discover.source_links(research["sources"])
        return AgentResult(
            agent=self.slug,
            summary=f"Language guide for {destination} ({lang_label})",
            data={"destination": destination, **data, "sources": sources},
        )
