"""Research / Travel-Intelligence Agent (spec §4.4).

Four-phase pipeline, ordered by the §9 rule *official API first, permitted public
pages second, never bypass access controls*:

  Phase A — Official APIs: YouTube Data API + Reddit public JSON (when keyed)
  Phase B — Camofox crawl: Google / Wikipedia / YouTube / Reddit search macros
  Phase C — LLM synthesis: structure everything into attractions, dining, safety
  Phase D — Halal verification: cross-check every dining pick against the
            certification directories before any confidence label is shown

Phase D is the honest part of the halal story (§7.5): an LLM saying "certified"
is not evidence, so `tools/halal.py` re-derives the label from JAKIM / HalalTrip
and a claim that cannot be corroborated is downgraded, never passed through.

Also computes the **Social Signal** score and **contradiction detection** from
§3.2 — both explicitly labelled Journava-derived, not objective measures.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from decimal import Decimal
from typing import Any
from urllib.parse import quote_plus

from app.agents.base import BaseAgent
from app.agents.prompts import research_messages
from app.agents.schemas import AgentResult, Option, Scope, TravelerProfile, TripRequest
from app.brain import knowledge
from app.core.llm import LLMUnavailableError, complete
from app.tools import camofox, halal, imagery, reddit, youtube

logger = logging.getLogger(__name__)

#: Confidence ranking — a verified label may only move a claim *down* this list
#: unless a certification body corroborates it.
_CONFIDENCE_RANK = {"certified": 2, "muslim_friendly": 1, "unverified": 0}


def _maps_link(name: str, destination: str) -> str:
    """A guaranteed 'View' target: a Google Maps search for the place, so every
    card has a working button even when no provider URL was found."""
    query = f"{name} {destination}".strip()
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(query)


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
        # Phase A — Official APIs first (§9 rule). Both are optional: a missing
        # key returns None and the crawl in Phase B covers the same ground.
        # ------------------------------------------------------------------ #
        self.emit("working", f"Querying official APIs for {destination}")
        api_sources, social = await self._official_apis(destination, profile)

        # ------------------------------------------------------------------ #
        # Phase B — Web research via Camofox (discovery + verification)
        # ------------------------------------------------------------------ #
        crawled_sources: dict[str, str] = dict(api_sources)

        if await camofox.available():
            self.emit("working", f"Camofox: researching {destination} across the web...")
            halal = "halal" if profile.halal_required else ""
            # All four crawls hit different engines/hosts, so run them at once
            # rather than one-after-another (this was the Tier-1 long pole).
            # Web search uses the default (DuckDuckGo) macro — the @google_search
            # path is consent/robots-walled and returned nothing while still
            # costing a round-trip.
            # Lead with the "top attractions" query so the crawl grounds the LLM
            # in the destination's actual signature landmarks (not generic filler).
            top_q, web_q, wiki_q, yt_q, reddit_q = (
                (f"top must-see tourist attractions in {destination} best things to do", None, 3200, "top"),
                (f"{destination} travel guide {halal} {interests_str}", None, 2600, "web"),
                (destination, "@wikipedia_search", 3000, "wikipedia"),
                (f"{destination} travel vlog {'halal food' if profile.halal_required else ''}", "@youtube_search", 2000, "youtube"),
                (f"{destination} travel tips", "@reddit_search", 2000, "reddit"),
            )
            queries = [top_q, web_q, wiki_q, yt_q, reddit_q]

            async def _crawl(query: str, macro: str | None, cap: int) -> str | None:
                res = await (camofox.search(query, macro=macro) if macro else camofox.search(query))
                return res[:cap] if res else None

            results = await asyncio.gather(
                *(_crawl(q, macro, cap) for (q, macro, cap, _key) in queries),
                return_exceptions=True,
            )
            for (_q, _macro, _cap, key), res in zip(queries, results):
                if isinstance(res, str) and res:
                    crawled_sources[key] = res

            n_sources = len(crawled_sources)
            self.emit("active", f"Camofox: gathered {n_sources} real sources")
        else:
            self.emit("working", f"Camofox unavailable — using LLM generation for {destination}")

        # ------------------------------------------------------------------ #
        # Phase C — LLM synthesis (with API + crawled data as context)
        # ------------------------------------------------------------------ #
        data = await self._synthesize(request, profile, crawled_sources)

        # ------------------------------------------------------------------ #
        # Phase D — Halal verification against certification directories
        # ------------------------------------------------------------------ #
        warnings: list[str] = []
        if data.get("dining"):
            data["dining"], halal_warnings = await self._verify_halal(
                data["dining"], destination, halal_required=profile.halal_required
            )
            warnings.extend(halal_warnings)

        # Social Signal + contradiction detection (§3.2) — Journava-derived.
        data["social_signal"] = social
        data["contradictions"] = self._detect_contradictions(data)

        # Top video reviews (YouTube most-viewed + TikTok best-effort) for the
        # "video reviews" tab of the places/food sections.
        data["video_reviews"] = await self._video_reviews(destination, profile)

        # A real destination photo for the trip thumbnail (keyless, Wikipedia).
        data["hero_image"] = await imagery.destination_image(destination)

        # Build option list from attractions + dining (for the Research Board tab)
        options = self._build_options(
            data, request.budget_currency, destination, sourced=bool(crawled_sources)
        )

        # Count items for summary
        n_attractions = len(data.get("attractions", []))
        n_dining = len(data.get("dining", []))
        source_label = f"{len(crawled_sources)} live sources" if crawled_sources else "LLM"
        summary = (
            f"{n_attractions} attractions, {n_dining} dining picks for "
            f"{destination} (via {source_label})"
        )
        if data.get("sentiment_summary"):
            summary += f" — {data['sentiment_summary']}"

        if profile.halal_required:
            warnings.append(
                "Halal labels are evidence-based: 'certified' requires a "
                "certification source, otherwise the pick is downgraded."
            )

        return AgentResult(
            agent=self.slug,
            summary=summary,
            options=options,
            applied_preferences=applied,
            warnings=warnings,
            data={**data, "sources_crawled": list(crawled_sources.keys())},
        )

    # ---------------------------------------------------------------------- #
    # Phase A — official APIs + Social Signal
    # ---------------------------------------------------------------------- #

    async def _official_apis(
        self,
        destination: str,
        profile: TravelerProfile,
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """Query YouTube + Reddit through their official APIs.

        Returns (source_text_by_name, social_signal). Both APIs are optional —
        an absent key yields None and the caller carries on.
        """
        food_qualifier = "halal food" if profile.halal_required else "food"
        videos, posts = await asyncio.gather(
            youtube.search_videos(f"{destination} travel guide {food_qualifier}", max_results=5),
            reddit.search(f"{destination} travel tips", limit=10),
        )

        sources: dict[str, str] = {}
        stats: list[dict[str, Any]] = []

        if videos:
            stats = await youtube.video_stats([v["video_id"] for v in videos]) or []
            views = {s["video_id"]: s for s in stats}
            sources["youtube_api"] = "\n".join(
                f"- {v['title']} ({v['channel']}, "
                f"{views.get(v['video_id'], {}).get('view_count', 0):,} views)"
                for v in videos
            )
            self.emit("active", f"YouTube API: {len(videos)} videos")

        if posts:
            sources["reddit_api"] = "\n".join(
                f"- r/{p['subreddit']} ({p['score']} pts, {p['num_comments']} comments): "
                f"{p['title']} — {p['selftext'][:200]}"
                for p in posts
            )
            self.emit("active", f"Reddit API: {len(posts)} threads")

        return sources, self._social_signal(videos or [], stats, posts or [])

    @staticmethod
    def _social_signal(
        videos: list[dict[str, Any]],
        video_stats: list[dict[str, Any]],
        posts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Journava-derived popularity score in [0, 1] (spec §3.2).

        Explicitly **not** an objective measure — it is a normalised blend of
        YouTube reach and Reddit discussion volume, surfaced with that caveat so
        nobody mistakes it for a rating.
        """
        total_views = sum(s.get("view_count", 0) for s in video_stats)
        total_score = sum(p.get("score", 0) for p in posts)
        total_comments = sum(p.get("num_comments", 0) for p in posts)

        # Log-ish normalisation: 1M views or 5k upvotes saturates the component.
        video_component = min(1.0, total_views / 1_000_000) if total_views else 0.0
        reddit_component = min(1.0, total_score / 5_000) if total_score else 0.0
        chatter_component = min(1.0, total_comments / 2_000) if total_comments else 0.0

        samples = [c for c in (video_component, reddit_component, chatter_component) if c]
        score = round(sum(samples) / len(samples), 2) if samples else None

        return {
            "score": score,
            "label": "Journava-derived, not an objective rating",
            "basis": {
                "youtube_videos": len(videos),
                "youtube_views": total_views,
                "reddit_threads": len(posts),
                "reddit_upvotes": total_score,
                "reddit_comments": total_comments,
            },
            "confidence": "low" if len(samples) < 2 else "medium",
        }

    # ---------------------------------------------------------------------- #
    # Phase D — halal verification + contradiction detection
    # ---------------------------------------------------------------------- #

    async def _verify_halal(
        self,
        dining: list[dict[str, Any]],
        destination: str,
        *,
        halal_required: bool,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Re-derive every halal label from the certification directories.

        The LLM's claim is treated as a *hypothesis*. `tools/halal.py` checks
        JAKIM / HalalTrip and heuristics; a claim the directories cannot support
        is downgraded to what the evidence shows. Nothing is ever upgraded to
        "certified" without a certification body naming it.
        """
        if not dining:
            return dining, []

        self.emit("working", f"Verifying halal status for {len(dining)} dining picks")
        checks = await halal.verify_batch(
            [{"title": d.get("title", ""), "country": destination} for d in dining]
        )

        warnings: list[str] = []
        downgraded = 0
        verified = 0

        for item, check in zip(dining, checks, strict=True):
            claimed = item.get("halal_confidence")
            evidence = check.get("confidence", "unverified")

            # Certification bodies are authoritative in both directions.
            if check.get("cert_body"):
                resolved = evidence
                verified += 1
            else:
                # No cert source: cap the claim at what evidence supports.
                claimed_rank = _CONFIDENCE_RANK.get(claimed or "unverified", 0)
                evidence_rank = _CONFIDENCE_RANK.get(evidence, 0)
                resolved = claimed if claimed_rank <= evidence_rank else evidence
                if claimed_rank > evidence_rank:
                    downgraded += 1

            item["halal_confidence"] = resolved
            item["halal_evidence"] = {
                "claimed": claimed,
                "resolved": resolved,
                "source": check.get("source"),
                "cert_body": check.get("cert_body"),
                "notes": check.get("notes", ""),
            }

        if downgraded:
            warnings.append(
                f"{downgraded} halal claim(s) downgraded — no certification "
                "source could corroborate them."
            )
        if verified:
            self.emit("active", f"Halal: {verified} corroborated by a certification body")
        if halal_required and not verified:
            warnings.append(
                "No dining pick could be confirmed against JAKIM/MUIS/HalalTrip — "
                "treat every label as unverified and confirm locally."
            )

        return dining, warnings

    @staticmethod
    def _detect_contradictions(data: dict[str, Any]) -> list[dict[str, str]]:
        """Surface conflicts between sources (spec §3.2).

        "Popular, but recent Reddit complaints about midday queues" is more
        useful than either signal alone, so disagreement is reported rather than
        averaged away.
        """
        contradictions: list[dict[str, str]] = []

        # The LLM is asked to flag these directly; pass through what it found.
        for raw in data.get("contradictions_detected") or []:
            if isinstance(raw, dict) and raw.get("claim"):
                contradictions.append(
                    {
                        "topic": str(raw.get("topic", "general")),
                        "claim": str(raw["claim"]),
                        "counter_claim": str(raw.get("counter_claim", "")),
                        "sources": str(raw.get("sources", "")),
                    }
                )

        # A high social signal alongside negative sentiment is itself a conflict.
        signal = (data.get("social_signal") or {}).get("score")
        sentiment = (data.get("sentiment_summary") or "").lower()
        negative = any(
            word in sentiment
            for word in ("crowd", "queue", "overrated", "complain", "scam", "avoid")
        )
        if signal is not None and signal >= 0.6 and negative:
            contradictions.append(
                {
                    "topic": "popularity vs experience",
                    "claim": f"High Social Signal ({signal}) — heavily discussed online",
                    "counter_claim": data.get("sentiment_summary", ""),
                    "sources": "YouTube/Reddit volume vs traveller sentiment",
                }
            )

        return contradictions

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

            # Feed back what the library already knows about this destination, so
            # picks build on prior findings instead of starting cold each time.
            learned = await knowledge.recall_text(request.destination)
            if learned:
                messages.append(
                    {
                        "role": "user",
                        "content": learned + "\n\nBuild on these prior findings; don't contradict them without reason.",
                    }
                )

            # Inject crawled data as additional context if available
            if crawled_sources:
                crawled_context = self._format_crawled_data(crawled_sources)
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "REAL WEB RESEARCH DATA (use this as your primary source, "
                            "cross-reference with your knowledge):\n\n"
                            f"{crawled_context}\n\n"
                            "Now generate the destination intelligence JSON using the "
                            "real data above. Attribute specific facts to their source "
                            "(e.g. reasoning: 'per Wikipedia' or 'per Reddit travelers')."
                        ),
                    }
                )

            raw_text = await complete(messages, response_format={"type": "json_object"})
            data = json.loads(raw_text)
            # Ensure required keys exist
            data.setdefault("attractions", [])
            data.setdefault("dining", [])
            data.setdefault("safety_tips", [])
            data.setdefault("customs", [])
            data.setdefault("best_times", [])
            data.setdefault("sentiment_summary", "")
            data.setdefault("contradictions_detected", [])
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
                {
                    "title": f"Central Market — {dest}",
                    "kind": "market",
                    "reasoning": "Iconic local experience (fallback)",
                    "estimated_cost": 15.00,
                    "cost_currency": "MYR",
                },
                {
                    "title": f"Old Town Walking Tour — {dest}",
                    "kind": "landmark",
                    "reasoning": "Covers major historical sites (fallback)",
                    "estimated_cost": 0,
                    "cost_currency": "MYR",
                },
                {
                    "title": f"National Museum — {dest}",
                    "kind": "museum",
                    "reasoning": "Best overview of local culture (fallback)",
                    "estimated_cost": 10.00,
                    "cost_currency": "MYR",
                },
            ],
            "dining": [
                {
                    "title": f"Local Street Food Hub — {dest}",
                    "cuisine": "Local",
                    "halal_confidence": "muslim_friendly",
                    "reasoning": "Popular with locals (fallback)",
                    "estimated_cost": 20.00,
                    "cost_currency": "MYR",
                },
                {
                    "title": f"Riverside Restaurant — {dest}",
                    "cuisine": "Fusion",
                    "halal_confidence": "unverified",
                    "reasoning": "Scenic dining (fallback)",
                    "estimated_cost": 60.00,
                    "cost_currency": "MYR",
                },
            ],
            "safety_tips": [
                "Keep valuables secure in crowded areas",
                "Use registered taxi services",
            ],
            "customs": [
                "Remove shoes before entering temples/homes",
                "Tipping is appreciated but not mandatory",
            ],
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
    def _build_options(
        data: dict[str, Any],
        currency: str,
        destination: str,
        *,
        sourced: bool,
    ) -> list[Option]:
        """Convert attractions + dining into Option objects.

        Each carries a **source tag** (Camofox when the crawl produced real
        sources, else the LLM), a **price** (or price range in `raw`), a review
        snippet, and always a **link** — the item's own URL when present, or a
        Google Maps search as a guaranteed "View" target so every card is clickable.
        """
        default_source = "camofox" if sourced else "llm"
        attractions: list[Option] = []
        dining: list[Option] = []

        for index, item in enumerate(data.get("attractions", [])):
            title = item.get("title", "Attraction")
            url = item.get("url") or item.get("link")
            link = url or _maps_link(title, destination)
            src = "camofox" if (sourced and url) else default_source
            attractions.append(
                Option(
                    id=f"RSH-A{index + 1:03d}",
                    kind="activity",
                    title=title,
                    price_amount=Decimal(str(item["estimated_cost"]))
                    if item.get("estimated_cost")
                    else None,
                    price_currency=item.get("cost_currency", currency),
                    reasoning=item.get("review") or item.get("reasoning"),
                    provider=item.get("category") or item.get("kind") or "Things to do",
                    source=src,
                    source_url=link,
                    booking_url=link,
                    raw={
                        "source": src,
                        "kind": item.get("kind", "attraction"),
                        "price_range": item.get("price_range"),
                        "rating": item.get("rating"),
                        "review": item.get("review"),
                    },
                )
            )

        for index, item in enumerate(data.get("dining", [])):
            title = item.get("title", "Restaurant")
            url = item.get("url") or item.get("link")
            link = url or _maps_link(title, destination)
            src = "camofox" if (sourced and url) else default_source
            dining.append(
                Option(
                    id=f"RSH-D{index + 1:03d}",
                    kind="restaurant",
                    title=title,
                    price_amount=Decimal(str(item["estimated_cost"]))
                    if item.get("estimated_cost")
                    else None,
                    price_currency=item.get("cost_currency", currency),
                    reasoning=item.get("review") or item.get("reasoning"),
                    provider=item.get("cuisine") or "Dining",
                    halal_confidence=item.get("halal_confidence"),
                    source=src,
                    source_url=link,
                    booking_url=link,
                    # `verified` here means "a certification body named it", which is
                    # the only claim strong enough to show without a caveat.
                    verified=bool((item.get("halal_evidence") or {}).get("cert_body")),
                    raw={
                        "source": src,
                        "cuisine": item.get("cuisine", ""),
                        "price_range": item.get("price_range"),
                        "rating": item.get("rating"),
                        "review": item.get("review"),
                        "halal_evidence": item.get("halal_evidence", {}),
                    },
                )
            )

        # Surface the strongest picks first instead of raw LLM order: higher
        # rating, corroborated by a real source link, has a review snippet, and
        # (for dining) stronger halal evidence.
        _HALAL_RANK = {"certified": 3, "verified": 3, "likely": 2, "unverified": 1}

        def _place_score(o: Option) -> float:
            raw = o.raw or {}
            rating = float(raw.get("rating") or 0)
            real_url = bool(o.source_url and "google.com/maps" not in (o.source_url or ""))
            has_review = bool(raw.get("review"))
            halal = _HALAL_RANK.get(str(o.halal_confidence or "").lower(), 0)
            # Higher is better → negate for an ascending sort (stable: ties keep
            # the LLM's own order).
            return -(rating * 2.0 + (1.0 if real_url else 0.0) + (0.5 if has_review else 0.0) + halal * 0.5)

        attractions.sort(key=_place_score)
        dining.sort(key=_place_score)
        return attractions + dining

    # ---------------------------------------------------------------------- #
    # Video reviews — YouTube (most-viewed) + TikTok (best-effort)
    # ---------------------------------------------------------------------- #

    async def _video_reviews(
        self,
        destination: str,
        profile: TravelerProfile,
    ) -> dict[str, list[dict[str, Any]]]:
        """Top short-video reviews for the destination's places and food.

        YouTube is the dependable source (official API, ranked by real view
        count). TikTok is added best-effort by scraping public search results —
        it may return nothing behind a bot-wall, and that is fine.
        """
        food_q = "halal food" if profile.halal_required else "food"
        yt_attr, yt_food, tt_attr, tt_food = await asyncio.gather(
            self._youtube_top(f"{destination} top attractions things to do"),
            self._youtube_top(f"{destination} best {food_q} where to eat"),
            self._tiktok_top(f"{destination} things to do"),
            self._tiktok_top(f"{destination} {food_q}"),
        )
        # TikTok first (the requested focus), then YouTube most-viewed for breadth.
        return {
            "attractions": (tt_attr + yt_attr)[:6],
            "food": (tt_food + yt_food)[:6],
        }

    async def _youtube_top(self, query: str) -> list[dict[str, Any]]:
        videos = await youtube.search_videos(query, max_results=6) or []
        if not videos:
            return []
        stats = await youtube.video_stats([v["video_id"] for v in videos]) or []
        views = {s["video_id"]: s.get("view_count", 0) for s in stats}
        out = [
            {
                "platform": "youtube",
                "id": v["video_id"],
                "title": v["title"],
                "channel": v.get("channel"),
                "thumbnail": v.get("thumbnail"),
                "views": views.get(v["video_id"], 0),
                "embed_url": f"https://www.youtube.com/embed/{v['video_id']}",
                "watch_url": f"https://www.youtube.com/watch?v={v['video_id']}",
            }
            for v in videos
        ]
        out.sort(key=lambda x: x["views"], reverse=True)
        return out[:4]

    async def _tiktok_top(self, query: str) -> list[dict[str, Any]]:
        """Best-effort TikTok clips via a Camofox `site:tiktok.com` Google search.

        TikTok's own search is bot-walled, but Google readily lists public
        `tiktok.com/@user/video/{id}` links, which Camofox reads from both the
        result snapshot and the extracted link URLs. Each id is embedded with
        TikTok's official iframe player (`/player/v1/{id}`).
        """
        try:
            if not await camofox.available():
                return []
            # DuckDuckGo's HTML endpoint is crawlable (Google's /search is a
            # consent wall for the headless browser) and lists real tiktok URLs.
            result = await camofox.search_with_sources(
                f"{query} site:tiktok.com", macro="@duckduckgo_search"
            )
            snapshot = (result or {}).get("snapshot") or ""
            sources = (result or {}).get("sources") or []
            haystack = snapshot + " " + " ".join(sources)

            seen: dict[str, str] = {}
            for path, vid in re.findall(r"(tiktok\.com/@[\w.-]+/video/(\d{6,}))", haystack):
                seen.setdefault(vid, f"https://www.{path}")
            for vid in re.findall(r"tiktok\.com/(?:embed|video|v)/(\d{6,})", haystack):
                seen.setdefault(vid, f"https://www.tiktok.com/embed/v2/{vid}")

            return [
                {
                    "platform": "tiktok",
                    "id": vid,
                    "title": "TikTok review",
                    "thumbnail": None,
                    "views": 0,
                    # Official embeddable iframe player.
                    "embed_url": f"https://www.tiktok.com/player/v1/{vid}?music_info=1&description=1",
                    "watch_url": watch,
                }
                for vid, watch in list(seen.items())[:3]
            ]
        except Exception as exc:  # noqa: BLE001 — TikTok is strictly best-effort
            logger.debug("TikTok lookup failed: %s", exc)
            return []
