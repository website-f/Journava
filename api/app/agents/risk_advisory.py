"""Risk Advisory Agent — detects active threats and predicts safe travel windows.

This is the "killer agent" for safety: uses GDELT (real-time global news database)
to detect conflicts, natural disasters, political unrest, and epidemics at the
destination. If a destination is currently dangerous, it predicts when conditions
will improve and suggests alternative safe periods.

Data sources: GDELT (events + tone), LLM analysis, REST Countries context.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm
from app.tools import gdelt, rest_countries

logger = logging.getLogger(__name__)

SAFETY_SYSTEM = """You are Journava's Risk Advisory agent. Analyze the safety situation
for a travel destination based on recent news events and country data.

Assess:
1. Active threats (conflict, war, terrorism, civil unrest, natural disasters, epidemics)
2. Overall safety level: "safe", "caution", or "dangerous"
3. If dangerous: predict which months would be safer based on seasonal/historical patterns
4. Specific advisories for travelers

Respond in JSON only:
{
  "safety_level": "safe|caution|dangerous",
  "active_threats": ["threat1", "threat2"],
  "advisory_text": "Brief advisory for the traveler",
  "safe_months": ["month1", "month2"],
  "confidence": 0.0-1.0,
  "recommended_action": "proceed|delay|avoid"
}"""

SAFETY_USER = """Destination: {destination}
Travel dates: {dates}
Recent news events in this region:
{events_summary}

Country info:
{country_info}

Media tone (negative = instability): avg_tone={avg_tone}, articles={num_articles}
Threat keywords detected: {threat_keywords}

Analyze the safety situation and provide your assessment."""


class RiskAdvisoryAgent(BaseAgent):
    slug = "risk_advisory"
    name = "Risk Advisory"
    role = "GDELT threat detection · safety assessment · travel windows"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        destination = request.destination or "unknown"
        dates = f"{request.start_date} to {request.end_date}" if request.start_date else "flexible"

        # 1. Fetch GDELT events and tone analysis
        news_events = await gdelt.events(destination, days=14)
        tone_data = await gdelt.tone_analysis(destination, days=14)
        keywords = await gdelt.threat_keywords(destination, days=14)

        # 2. Fetch country info from REST Countries
        country = await rest_countries.country_info(destination)

        # 3. Build events summary for LLM
        events_summary = (
            "\n".join(f"- {e.get('title', 'Unknown')}" for e in news_events[:10])
            or "No recent news events found."
        )

        country_info_str = json.dumps(country) if country else "Not available"

        # 4. LLM analysis of safety situation
        try:
            response = await llm.complete(
                [
                    {"role": "system", "content": SAFETY_SYSTEM},
                    {
                        "role": "user",
                        "content": SAFETY_USER.format(
                            destination=destination,
                            dates=dates,
                            events_summary=events_summary,
                            country_info=country_info_str,
                            avg_tone=tone_data.get("avg_tone", 0),
                            num_articles=tone_data.get("num_articles", 0),
                            threat_keywords=", ".join(keywords) or "none",
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                agent="risk_advisory",
            )
            assessment = json.loads(response)
        except Exception:  # noqa: BLE001
            assessment = self._fallback_assessment(destination, keywords)

        # 5. Build result
        safety_level = assessment.get("safety_level", "caution")
        warnings: list[str] = []

        if safety_level == "dangerous":
            warnings.append(
                f"TRAVEL ADVISORY: {destination} is currently assessed as DANGEROUS. "
                f"Active threats: {', '.join(assessment.get('active_threats', ['unknown']))}"
            )
            safe_months = assessment.get("safe_months", [])
            if safe_months:
                warnings.append(f"Suggested safer months: {', '.join(safe_months)}")
        elif safety_level == "caution":
            warnings.append(
                f"Travel to {destination} requires caution. {assessment.get('advisory_text', '')}"
            )

        self.emit(
            "active",
            f"Safety: {safety_level.upper()}",
            data={
                "safety_level": safety_level,
                "active_threats": assessment.get("active_threats", []),
            },
        )

        return AgentResult(
            agent=self.slug,
            summary=assessment.get(
                "advisory_text", f"Safety assessment for {destination}: {safety_level}"
            ),
            warnings=warnings,
            data={
                "safety_level": safety_level,
                "active_threats": assessment.get("active_threats", []),
                "safe_months": assessment.get("safe_months", []),
                "recommended_action": assessment.get("recommended_action", "proceed"),
                "confidence": assessment.get("confidence", 0.5),
                "gdelt_events_count": len(news_events),
                "avg_media_tone": tone_data.get("avg_tone", 0),
                "threat_keywords": keywords,
                "country_region": country.get("region", "") if country else "",
            },
        )

    def _fallback_assessment(self, destination: str, keywords: list[str]) -> dict:
        """Fallback when LLM is unavailable — heuristic-based assessment."""
        HIGH_RISK_KEYWORDS = {"conflict", "war", "attack", "terror", "epidemic"}
        MEDIUM_RISK_KEYWORDS = {"protest", "unrest", "flood", "earthquake", "hurricane"}

        high_hits = set(keywords) & HIGH_RISK_KEYWORDS
        medium_hits = set(keywords) & MEDIUM_RISK_KEYWORDS

        if high_hits:
            return {
                "safety_level": "dangerous",
                "active_threats": list(high_hits),
                "advisory_text": f"Active high-risk events detected in {destination}.",
                "safe_months": [],
                "confidence": 0.6,
                "recommended_action": "avoid",
            }
        elif medium_hits:
            return {
                "safety_level": "caution",
                "active_threats": list(medium_hits),
                "advisory_text": f"Exercise caution when traveling to {destination}.",
                "safe_months": [],
                "confidence": 0.5,
                "recommended_action": "delay",
            }
        return {
            "safety_level": "safe",
            "active_threats": [],
            "advisory_text": f"No major safety concerns detected for {destination}.",
            "safe_months": [],
            "confidence": 0.7,
            "recommended_action": "proceed",
        }
