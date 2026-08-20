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
from urllib.parse import quote_plus

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import llm
from app.tools import camofox, gdelt, rest_countries

logger = logging.getLogger(__name__)

#: News keywords → severity (3 high · 2 medium · 1 low). Scanned in the live
#: Camofox crawl so an active war/disaster/unrest story surfaces as an alert.
_ALERT_KEYWORDS: dict[str, int] = {
    "war": 3, "warfare": 3, "conflict": 3, "invasion": 3, "airstrike": 3,
    "attack": 3, "terror": 3, "bombing": 3, "shooting": 3, "evacuat": 3,
    "martial law": 3, "outbreak": 3, "epidemic": 3, "pandemic": 3,
    "state of emergency": 3, "coup": 3,
    "earthquake": 2, "typhoon": 2, "cyclone": 2, "hurricane": 2, "tsunami": 2,
    "volcano": 2, "eruption": 2, "flood": 2, "landslide": 2, "wildfire": 2,
    "storm": 2, "protest": 2, "riot": 2, "unrest": 2, "curfew": 2,
    "travel warning": 2, "travel advisory": 2, "lockdown": 2, "quarantine": 2,
}
_SEVERITY_LABEL = {3: "high", 2: "medium", 1: "low"}

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

        # 4b. Live news crawl (Camofox) — concrete, linkable headlines about war,
        # disaster or unrest at the destination during the travel window.
        when_label = (
            request.start_date.strftime("%B %Y") if request.start_date else ""
        )
        self.emit("working", f"Camofox: checking live news for {destination}")
        news_alerts, news_checked, news_search_url = await self._news_alerts(
            destination, when_label
        )
        news_severity = max((a["level"] for a in news_alerts), default=0)
        if news_alerts:
            self.emit(
                "active",
                f"News: {len(news_alerts)} alert(s) found for {destination}",
                data={"top": news_alerts[0]["headline"][:80]},
            )
        elif news_checked:
            self.emit("active", f"News: no war/disaster/unrest found for {destination}")

        # 5. Build result
        safety_level = assessment.get("safety_level", "caution")
        # A live high-severity story escalates an otherwise-"safe" read to caution.
        if news_severity >= 3 and safety_level == "safe":
            safety_level = "caution"
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
        if news_alerts and news_severity >= 2:
            warnings.append(
                f"Recent news for {destination}: {news_alerts[0]['headline'][:140]}"
            )

        # Single traveller-facing verdict combining the assessment + live news.
        verdict = "clear" if (safety_level == "safe" and news_severity < 2) else (
            "avoid" if safety_level == "dangerous" or news_severity >= 3 else "caution"
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
                "verdict": verdict,
                "active_threats": assessment.get("active_threats", []),
                "safe_months": assessment.get("safe_months", []),
                "recommended_action": assessment.get("recommended_action", "proceed"),
                "confidence": assessment.get("confidence", 0.5),
                "gdelt_events_count": len(news_events),
                "avg_media_tone": tone_data.get("avg_tone", 0),
                "threat_keywords": keywords,
                "country_region": country.get("region", "") if country else "",
                # Live news crawl
                "news_checked": news_checked,
                "news_alerts": news_alerts,
                "news_search_url": news_search_url,
                "travel_window": when_label,
            },
        )

    # ------------------------------------------------------------------ #
    # Live news crawl (Camofox)
    # ------------------------------------------------------------------ #

    async def _news_alerts(
        self,
        destination: str,
        when_label: str,
    ) -> tuple[list[dict[str, Any]], bool, str | None]:
        """Crawl live news for war / disaster / unrest at the destination.

        Returns (alerts, checked, search_url). `checked` is True whenever the
        crawl ran (so "nothing found" can be shown as a positive "all clear"
        rather than "not checked"). Each alert carries a headline, a severity and
        the source link the traveller can open to verify.
        """
        if not await camofox.available():
            return [], False, None

        window = when_label or "latest"
        # Concise queries only — DuckDuckGo's HTML endpoint returns an empty page
        # for long OR-chains, which would masquerade as a false "all clear".
        queries = [
            f"{destination} travel safety advisory news {window}".strip(),
            f"{destination} news {window}".strip(),
            f"{destination} travel warning",
        ]
        snapshot = ""
        sources: list[str] = []
        used_query = queries[0]
        for query in queries:
            try:
                result = await camofox.search_with_sources(query, macro="@duckduckgo_search")
            except Exception as exc:  # noqa: BLE001 — news is best-effort
                logger.debug("News crawl failed for %r: %s", query, exc)
                continue
            snapshot = (result or {}).get("snapshot") or ""
            sources = [
                s for s in ((result or {}).get("sources") or [])
                if s.startswith("http") and "duckduckgo" not in s
            ]
            used_query = query
            if snapshot:
                break

        search_url = "https://duckduckgo.com/?q=" + quote_plus(used_query)

        # Only claim we "checked" when we actually got a page back — otherwise the
        # UI shows "check unavailable" rather than a misleading all-clear.
        if not snapshot:
            return [], False, search_url

        alerts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_line in snapshot.splitlines():
            line = raw_line.strip()
            if not (20 <= len(line) <= 200):
                continue
            lower = line.lower()
            level = max(
                (sev for kw, sev in _ALERT_KEYWORDS.items() if kw in lower), default=0
            )
            if level == 0:
                continue
            key = lower[:80]
            if key in seen:
                continue
            seen.add(key)
            alerts.append(
                {
                    "headline": line,
                    "level": level,
                    "severity": _SEVERITY_LABEL[level],
                    "url": sources[len(alerts)] if len(alerts) < len(sources) else search_url,
                }
            )
            if len(alerts) >= 6:
                break

        alerts.sort(key=lambda a: a["level"], reverse=True)
        return alerts, True, search_url

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
