"""Research / Travel-Intelligence Agent (spec §4.4).

Real web research via Camofox Browser (stealth headless Firefox with C++
anti-detection) + LLM synthesis. Three-phase pipeline:

  Phase A — Camofox crawl: Google, Wikipedia, YouTube, Reddit search macros
  Phase B — LLM synthesis: structure crawled data into attractions, dining, safety
  Phase C — Fallback: LLM-only generation, then static mock data

Camofox uses search macros (@google_search, @youtube_search, @reddit_search,
@wikipedia_search) that produce accessibility snapshots — token-efficient and
bypass bot detection via Camoufox's C++ fingerprint spoofing.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts import research_messages
from app.agents.schemas import AgentResult, Option, Scope, TravelerProfile, TripRequest
from app.core.llm import LLMUnavailableError, complete
from app.tools import camofox

logger = logging.getLogger(__name__)


class ResearchAgent(BaseAgent):
    slug = "research"
    name = "Research"
    role = "Camofox · YouTube · Reddit"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        applied: dict[str, Scope] = {}

        if profile.halal_required:
            applied["halal_required"] = "hard_filter"
        if profile.allergies:
            applied["allergies"] = "hard_filter"
        if profile.interests:
            applied["interests"] = "soft_ranking"

        destination = request.destination or "unknown"
        interests_str = ", ".join(profile.interests) if profile.interests else "general travel"

        # ------------------------------------------------------------------ #
        # Phase A — Real web crawling via Camofox
        # ------------------------------------------------------------------ #
        crawled_sources: dict[str, str] = {}

        if await camofox.available():
            self.emit("working", f"Camofox: crawling Google for {destination}...")
            google_result = await camofox.search(
                f"{destination} travel guide {'halal' if profile.halal_required else ''} {interests_str}",
                macro="@google_search",
            )
            if google_result:
                crawled_sources["google"] = google_result[:3000]

            self.emit("working", f"Camofox: searching Wikipedia for {destination}...")
            wiki_result = await camofox.search(destination, macro="@wikipedia_search")
            if wiki_result:
                crawled_sources["wikipedia"] = wiki_result[:3000]

            self.emit("working", f"Camofox: searching YouTube for {destination} travel...")
            youtube_result = await camofox.search(
                f"{destination} travel vlog {'halal food' if profile.halal_required else ''}",
                macro="@youtube_search",
            )
            if youtube_result:
                crawled_sources["youtube"] = youtube_result[:2000]

            self.emit("working", f"Camofox: searching Reddit for {destination} tips...")
            reddit_result = await camofox.search(
                f"{destination} travel tips",
                macro="@reddit_search",
            )
            if reddit_result:
                crawled_sources["reddit"] = reddit_result[:2000]

            n_sources = len(crawled_sources)
            self.emit("active", f"Camofox: gathered {n_sources} real sources")
        else:
            self.emit("working", f"Camofox unavailable — using LLM generation for {destination}")

        # ------------------------------------------------------------------ #
        # Phase B — LLM synthesis (with crawled data as context)
        # ------------------------------------------------------------------ #
        data = await self._synthesize(request, profile, crawled_sources)

        # Build option list from attractions + dining (for the Research Board tab)
        options = self._build_options(data, request.budget_currency)

        # Count items for summary
        n_attractions = len(data.get("attractions", []))
        n_dining = len(data.get("dining", []))
        source_label = f"{len(crawled_sources)} live sources" if crawled_sources else "LLM"
        summary = f"{n_attractions} attractions, {n_dining} dining picks for {destination} (via {source_label})"
        if data.get("sentiment_summary"):
            summary += f" — {data['sentiment_summary']}"

        return AgentResult(
            agent=self.slug,
            summary=summary,
            options=options,
            applied_preferences=applied,
            warnings=(
                ["Halal results carry a confidence label — never an unverified claim"]
                if profile.halal_required
                else []
            ),
            data={**data, "sources_crawled": list(crawled_sources.keys())},
        )

    # ---------------------------------------------------------------------- #
    # Phase B — LLM synthesis
    # ---------------------------------------------------------------------- #

    async def _synthesize(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        crawled_sources: dict[str, str],
    ) -> dict[str, Any]:
        """Synthesize crawled data + LLM into structured intelligence."""
        try:
            messages = research_messages(request, profile)

            # Inject crawled data as additional context if available
            if crawled_sources:
                crawled_context = self._format_crawled_data(crawled_sources)
                messages.append({
                    "role": "user",
                    "content": (
                        "REAL WEB RESEARCH DATA (use this as your primary source, "
                        "cross-reference with your knowledge):\n\n"
                        f"{crawled_context}\n\n"
                        "Now generate the destination intelligence JSON using the "
                        "real data above. Attribute specific facts to their source "
                        "(e.g. reasoning: 'per Wikipedia' or 'per Reddit travelers')."
                    ),
                })

            raw_text = await complete(messages, response_format={"type": "json_object"})
            data = json.loads(raw_text)
            # Ensure required keys exist
            data.setdefault("attractions", [])
            data.setdefault("dining", [])
            data.setdefault("safety_tips", [])
            data.setdefault("customs", [])
            data.setdefault("best_times", [])
            data.setdefault("sentiment_summary", "")
            return data
        except (LLMUnavailableError, json.JSONDecodeError) as exc:
            logger.warning("Research LLM synthesis failed: %s", exc)
            self.emit("waiting", f"LLM unavailable: {type(exc).__name__}")
            return self._fallback_intelligence(request.destination)

    # ---------------------------------------------------------------------- #
    # Phase C — Fallback (LLM-only, then static)
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _fallback_intelligence(destination: str | None) -> dict[str, Any]:
        """Static intelligence when both Camofox and LLM are unavailable."""
        dest = destination or "your destination"
        return {
            "attractions": [
                {"title": f"Central Market — {dest}", "kind": "market", "reasoning": "Iconic local experience (fallback)", "estimated_cost": 15.00, "cost_currency": "MYR"},
                {"title": f"Old Town Walking Tour — {dest}", "kind": "landmark", "reasoning": "Covers major historical sites (fallback)", "estimated_cost": 0, "cost_currency": "MYR"},
                {"title": f"National Museum — {dest}", "kind": "museum", "reasoning": "Best overview of local culture (fallback)", "estimated_cost": 10.00, "cost_currency": "MYR"},
            ],
            "dining": [
                {"title": f"Local Street Food Hub — {dest}", "cuisine": "Local", "halal_confidence": "muslim_friendly", "reasoning": "Popular with locals (fallback)", "estimated_cost": 20.00, "cost_currency": "MYR"},
                {"title": f"Riverside Restaurant — {dest}", "cuisine": "Fusion", "halal_confidence": "unverified", "reasoning": "Scenic dining (fallback)", "estimated_cost": 60.00, "cost_currency": "MYR"},
            ],
            "safety_tips": ["Keep valuables secure in crowded areas", "Use registered taxi services"],
            "customs": ["Remove shoes before entering temples/homes", "Tipping is appreciated but not mandatory"],
            "best_times": ["Early morning for popular attractions", "Evening for street food"],
            "sentiment_summary": f"{dest} research via fallback data. Enable Camofox for live web intelligence.",
        }

    # ---------------------------------------------------------------------- #
    # Helpers
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _format_crawled_data(sources: dict[str, str]) -> str:
        """Format crawled sources into a readable context block for the LLM."""
        parts = []
        for source_name, content in sources.items():
            label = source_name.upper()
            parts.append(f"--- {label} ---\n{content}\n")
        return "\n".join(parts)

    @staticmethod
    def _build_options(data: dict[str, Any], currency: str) -> list[Option]:
        """Convert attractions + dining into Option objects for the Research Board."""
        options: list[Option] = []

        for item in data.get("attractions", []):
            options.append(Option(
                id=f"RSH-A{len(options)+1:03d}",
                kind="activity",
                title=item.get("title", "Attraction"),
                price_amount=Decimal(str(item["estimated_cost"])) if item.get("estimated_cost") else None,
                price_currency=item.get("cost_currency", currency),
                reasoning=item.get("reasoning"),
                raw={"source": "research", "kind": item.get("kind", "attraction")},
            ))

        for item in data.get("dining", []):
            options.append(Option(
                id=f"RSH-D{len(options)+1:03d}",
                kind="restaurant",
                title=item.get("title", "Restaurant"),
                price_amount=Decimal(str(item["estimated_cost"])) if item.get("estimated_cost") else None,
                price_currency=item.get("cost_currency", currency),
                reasoning=item.get("reasoning"),
                halal_confidence=item.get("halal_confidence"),
                raw={"source": "research", "cuisine": item.get("cuisine", "")},
            ))

        return options
