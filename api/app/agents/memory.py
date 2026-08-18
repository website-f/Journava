"""Memory Agent — Gnosion read/write (spec §4.8).

Loads the Traveler Profile before a run and writes accepted/rejected outcomes
back afterwards. That write-back is the self-improvement flywheel (§7 ③).
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent
from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.brain import gnosion_client

PROFILE_DOMAIN = "traveler_profile"
OUTCOME_DOMAIN = "decision_outcomes"


class MemoryAgent(BaseAgent):
    slug = "memory"
    name = "Memory"
    role = "Gnosion read / write"

    async def run(self, request: TripRequest, profile: TravelerProfile, *, context: dict[str, Any] | None = None) -> AgentResult:
        # Seed long-term memory with the standing preferences (§3.5).
        gnosion_client.remember(
            PROFILE_DOMAIN,
            key="current",
            value=profile.model_dump_json(),
        )

        return AgentResult(
            agent=self.slug,
            summary="Profile seeded into Gnosion",
            data={"brain_available": gnosion_client.available()},
        )

    @staticmethod
    def load_profile() -> TravelerProfile:
        """Recall the stored profile; an empty profile means "search globally"."""
        stored = gnosion_client.recall(PROFILE_DOMAIN, "current")
        if not stored:
            return TravelerProfile()
        try:
            raw = stored["value"] if isinstance(stored, dict) else stored
            return TravelerProfile.model_validate_json(raw)
        except Exception:  # noqa: BLE001 - never let a bad record break a run
            return TravelerProfile()

    @staticmethod
    def record_outcome(domain: str, recommendation: dict, accepted: bool) -> None:
        """Write an accepted/rejected decision back to the brain."""
        gnosion_client.remember(
            OUTCOME_DOMAIN,
            key=json.dumps(recommendation, default=str)[:200],
            value="accepted" if accepted else "rejected",
            label=domain,
        )
