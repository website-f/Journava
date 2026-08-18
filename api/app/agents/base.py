"""Base class for every specialist agent.

Adding an agent = subclass `BaseAgent`, implement `run`, register the node in
`app/graph/supervisor.py`. That is the whole "extensible ecosystem" story (§4).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.agents.schemas import AgentResult, TravelerProfile, TripRequest
from app.core import sse


class BaseAgent(ABC):
    """Common lifecycle: announce status on the SSE bus, then do the work."""

    #: Stable slug used by the SSE stream and the UI agent grid.
    slug: str = "agent"
    #: Human label shown in the Agent Control Center.
    name: str = "Agent"
    #: One-line role description.
    role: str = ""

    def emit(
        self,
        status: sse.AgentStatus,
        message: str,
        *,
        data: dict[str, Any] | None = None,
        caused_by: str | None = None,
    ) -> None:
        sse.publish(self.slug, status, message, data=data, caused_by=caused_by)

    async def __call__(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        caused_by: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        self.emit("working", f"{self.name} started", caused_by=caused_by)
        try:
            result = await self.run(request, profile, context=context)
        except Exception as exc:
            self.emit("error", f"{self.name} failed: {exc}")
            raise
        self.emit("active", result.summary or f"{self.name} finished")
        return result

    @abstractmethod
    async def run(
        self,
        request: TripRequest,
        profile: TravelerProfile,
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Do the agent's work.

        Read `profile` first: a relevant preference narrows the scope, its
        absence means search globally (§7.5).

        `context` carries accumulated results from upstream agents (populated
        only for sequential nodes like budget/itinerary/memory).
        """
        raise NotImplementedError
