"""Memory Agent — Gnosion read/write (spec §4.8).

Loads the Traveler Profile before a run and writes what the run learned back
afterwards. Two distinct writes matter here:

- **Profile seeding** — the standing preferences (§3.5) that every agent reads.
- **Experience capture** — the destination, the options that were surfaced, and
  the accepted/rejected decisions. This is the self-improvement flywheel (§7 ③);
  without it the brain graph stays empty and nothing gets smarter between trips.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.brain import gnosion_client

logger = logging.getLogger(__name__)

PROFILE_DOMAIN = "traveler_profile"
OUTCOME_DOMAIN = "decision_outcomes"

#: agent slug → brain domain, for capturing what each specialist surfaced.
_AGENT_DOMAINS: dict[str, str] = {
    "flight": "flights",
    "hotel": "hotels",
    "research": "destinations",
    "weather_risk": "weather",
    "budget": "budgets",
    "itinerary": "itinerary",
}


class MemoryAgent(BaseAgent):
    slug = "memory"
    name = "Memory"
    role = "Gnosion read / write"

    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        # Capture this run's experience so the next trip starts smarter. The
        # standing profile itself is written per-user by the /profile endpoint,
        # never re-seeded here — so one user's run can't clobber another's.
        written = self._capture_experience(request, context or {})

        snapshot = gnosion_client.snapshot()
        return AgentResult(
            agent=self.slug,
            summary=(f"{written} memories written ({snapshot['backend']})"),
            data={
                "brain_available": gnosion_client.available(),
                "backend": snapshot["backend"],
                "memories_written": written,
                "domains": snapshot["domains"],
            },
        )

    # ---------------------------------------------------------------------- #
    # Experience capture
    # ---------------------------------------------------------------------- #

    def _capture_experience(
        self,
        request: TripRequest,
        results: dict[str, Any],
    ) -> int:
        """Write one memory per upstream agent that produced something.

        Keyed by destination so recall on a repeat trip to the same place finds
        the previous run's findings.
        """
        destination = (
            request.destination
            or (results.get("chief", {}).get("data", {}) or {}).get("destination")
            or "unknown"
        )
        written = 0

        for slug, domain in _AGENT_DOMAINS.items():
            result = results.get(slug)
            if not result:
                continue
            payload = {
                "destination": destination,
                "summary": result.get("summary", ""),
                "option_titles": [o.get("title") for o in (result.get("options") or [])[:8]],
                "applied_preferences": result.get("applied_preferences", {}),
            }
            try:
                gnosion_client.remember(
                    domain,
                    key=destination.lower(),
                    value=json.dumps(payload, default=str),
                    label=slug,
                )
                written += 1
            except Exception as exc:  # noqa: BLE001 — memory is never fatal
                logger.warning("Could not write %s memory: %s", domain, exc)

        # Dining is its own domain: it is the one halal decisions live in.
        dining = [
            o
            for o in (results.get("research", {}).get("options") or [])
            if o.get("kind") == "restaurant"
        ]
        if dining:
            try:
                gnosion_client.remember(
                    "dining",
                    key=destination.lower(),
                    value=json.dumps(
                        [
                            {
                                "title": o.get("title"),
                                "halal_confidence": o.get("halal_confidence"),
                            }
                            for o in dining[:10]
                        ],
                        default=str,
                    ),
                    label="research",
                )
                written += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not write dining memory: %s", exc)

        return written

    # ---------------------------------------------------------------------- #
    # Static helpers used by the API layer
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _profile_key(user_id: str | None) -> str:
        """The brain key for a user's profile. Falls back to a shared key for
        unauthenticated/legacy callers so nothing breaks without a user id."""
        return f"user:{user_id}" if user_id else "current"

    @staticmethod
    def load_profile(user_id: str | None = None) -> TravelerProfile:
        """Recall a user's stored profile; an empty profile means "search globally"."""
        stored = gnosion_client.recall(PROFILE_DOMAIN, MemoryAgent._profile_key(user_id))
        if not stored:
            return TravelerProfile()
        try:
            raw = stored["value"] if isinstance(stored, dict) else stored
            return TravelerProfile.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001 — a bad record must not break a run
            logger.warning("Stored profile unreadable (%s) — searching globally", exc)
            return TravelerProfile()

    #: Interest cues we look for in a traveller's past goals to learn their taste.
    _TASTE_CUES = (
        "halal", "beach", "island", "temple", "shrine", "food", "foodie", "street food",
        "nature", "hiking", "mountain", "waterfall", "luxury", "budget", "backpack",
        "shopping", "nightlife", "culture", "museum", "history", "adventure", "romantic",
        "honeymoon", "family", "kids", "ski", "snow", "diving", "snorkel", "safari",
        "wildlife", "photography", "instagram", "cafe", "coffee", "wellness", "spa",
    )

    @staticmethod
    async def build_taste_profile(user_id: str | None) -> dict[str, Any]:
        """Learn a compact taste profile from the traveller's own history — the
        destinations they've saved and the interests recurring in their past
        goals — so every future plan is personalised to them, not generic.
        Heuristic + cheap (no LLM); safe/empty for a new or anonymous user."""
        from collections import Counter

        from app.core import db

        pool = await db.get_pool()
        if pool is None or not user_id:
            return {}
        import uuid as _uuid

        try:
            uid = _uuid.UUID(user_id)
            async with pool.acquire() as conn:
                trips = await conn.fetch(
                    "SELECT destination, snapshot FROM saved_results "
                    "WHERE user_id = $1 AND kind = 'trip' ORDER BY created_at DESC LIMIT 20",
                    uid,
                )
        except Exception as exc:  # noqa: BLE001 — personalisation is best-effort
            logger.info("taste profile query skipped: %s", exc)
            return {}

        visited: list[str] = []
        seen: set[str] = set()
        goal_text: list[str] = []
        for row in trips:
            dest = (row["destination"] or "").split(",")[0].strip()
            key = dest.lower()
            if dest and key not in seen:
                seen.add(key)
                visited.append(dest)
            # The goal that produced each saved trip is the richest taste signal.
            try:
                snap = row["snapshot"]
                snap = json.loads(snap) if isinstance(snap, str) else (snap or {})
                goal_text.append(str(((snap.get("chief") or {}).get("data") or {}).get("goal") or ""))
            except Exception:  # noqa: BLE001
                pass

        text = " ".join(goal_text).lower()
        counts = Counter(cue for cue in MemoryAgent._TASTE_CUES if cue in text)
        loves = [cue for cue, _ in counts.most_common(6)]
        if not loves and not visited:
            return {}
        return {"loves": loves, "visited": visited[:8]}

    @staticmethod
    def save_profile(profile: TravelerProfile, user_id: str | None = None) -> None:
        """Persist a user's standing preferences (seed of long-term memory, §3.5)."""
        gnosion_client.remember(
            PROFILE_DOMAIN,
            key=MemoryAgent._profile_key(user_id),
            value=profile.model_dump_json(),
        )

    @staticmethod
    def record_outcome(
        domain: str,
        recommendation: dict[str, Any] | str,
        accepted: bool,
    ) -> None:
        """Write an accepted/rejected decision back to the brain (§7 ③)."""
        item = (
            recommendation
            if isinstance(recommendation, str)
            else json.dumps(recommendation, default=str)
        )
        gnosion_client.record_outcome(domain, item[:200], accepted)

    @staticmethod
    def recall_destination(domain: str, destination: str) -> dict[str, Any] | None:
        """Recall what a previous trip to `destination` learned in `domain`."""
        stored = gnosion_client.recall(domain, destination.lower())
        if not stored:
            return None
        try:
            raw = stored["value"] if isinstance(stored, dict) else stored
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return None
