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
        # 1. Keep the standing preferences in long-term memory (§3.5). Only write
        # when they actually changed — Gnosion appends entries, so an
        # unconditional write per run would pile up identical copies and inflate
        # the brain graph's weights with no new information.
        current = profile.model_dump_json()
        if self._stored_profile_json() != current:
            gnosion_client.remember(PROFILE_DOMAIN, key="current", value=current)

        # 2. Capture this run's experience so the next trip starts smarter.
        written = self._capture_experience(request, context or {})

        snapshot = gnosion_client.snapshot()
        return AgentResult(
            agent=self.slug,
            summary=(f"Profile seeded · {written} memories written ({snapshot['backend']})"),
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

    @staticmethod
    def _stored_profile_json() -> str | None:
        """The raw profile JSON currently in the brain, if any."""
        stored = gnosion_client.recall(PROFILE_DOMAIN, "current")
        if not stored:
            return None
        raw = stored["value"] if isinstance(stored, dict) else stored
        return raw if isinstance(raw, str) else None

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
    def load_profile() -> TravelerProfile:
        """Recall the stored profile; an empty profile means "search globally"."""
        stored = gnosion_client.recall(PROFILE_DOMAIN, "current")
        if not stored:
            return TravelerProfile()
        try:
            raw = stored["value"] if isinstance(stored, dict) else stored
            return TravelerProfile.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001 — a bad record must not break a run
            logger.warning("Stored profile unreadable (%s) — searching globally", exc)
            return TravelerProfile()

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
