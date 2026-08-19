"""Task agents — the domain-agnostic half of the runtime.

A `TaskAgent` takes a plain JSON payload and returns a plain JSON result. It has
no idea what a trip is, which is the point: it's how the platform grows past
travel. Each declares `domain` + `capabilities` so the catalog and (later) the
orchestrator can route to it by what it does.

The first non-travel pack is `EmailReplierAgent` — proof that "hiring" a new
agent is: write a class, register it, done. No graph surgery, no trip schema.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from app.core import sse
from app.core.llm import LLMUnavailableError, complete

logger = logging.getLogger(__name__)


class TaskAgent(ABC):
    """A single-shot agent over an arbitrary JSON payload."""

    slug: str = "task"
    name: str = "Task Agent"
    role: str = ""
    domain: str = "general"
    capabilities: tuple[str, ...] = ()
    #: Fields the payload should contain, for the catalog + basic validation.
    input_fields: tuple[str, ...] = ()

    def emit(self, status: sse.AgentStatus, message: str, **data: Any) -> None:
        sse.publish(self.slug, status, message, data=data or None)

    @abstractmethod
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Do the work. Read from `payload`, return a JSON-serialisable dict."""
        raise NotImplementedError


class EmailReplierAgent(TaskAgent):
    """Draft a reply to an incoming email in a requested tone.

    Deliberately nothing to do with travel — it demonstrates that the runtime is
    a general agent platform, not a travel app with agents bolted on.
    """

    slug = "email_replier"
    name = "Email Replier"
    role = "Drafts a reply to an incoming email in your voice"
    domain = "productivity"
    capabilities = ("email.draft_reply", "text.rewrite")
    input_fields = ("email", "tone", "intent")

    _TONES = {"friendly", "formal", "concise", "warm", "firm", "apologetic"}

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        email = str(payload.get("email") or "").strip()
        if not email:
            return {"error": "No email text provided."}
        tone = str(payload.get("tone") or "friendly").lower()
        if tone not in self._TONES:
            tone = "friendly"
        intent = str(payload.get("intent") or "").strip()
        sender_name = str(payload.get("from_name") or "").strip()

        self.emit("working", f"Drafting a {tone} reply")

        system = (
            "You are an assistant that drafts email replies. Write only the reply "
            "body — no preamble, no explanation, no subject line unless asked. "
            f"Tone: {tone}. Keep it natural and human."
        )
        user = f"Incoming email:\n\"\"\"\n{email}\n\"\"\"\n"
        if intent:
            user += f"\nWhat I want to say / do: {intent}\n"
        if sender_name:
            user += f"\nSign off as: {sender_name}\n"
        user += "\nWrite the reply body now."

        try:
            reply = await complete(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.5,
                agent=self.slug,
            )
        except LLMUnavailableError as exc:
            self.emit("error", "No AI model available")
            return {"error": f"No AI model is configured: {exc}"}

        reply = reply.strip()
        self.emit("active", "Reply drafted")
        return {
            "reply": reply,
            "tone": tone,
            "word_count": len(reply.split()),
            "intent": intent or None,
        }


#: Registered task agents — the "hire" point. Add a class, add it here, done.
TASK_REGISTRY: dict[str, TaskAgent] = {
    agent.slug: agent
    for agent in (EmailReplierAgent(),)
}


async def run_task(slug: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Execute a task agent by slug. Raises KeyError for an unknown agent."""
    agent = TASK_REGISTRY[slug]
    logger.info("Running task agent %s", slug)
    return await agent.run(payload)


def describe_task_agents() -> list[dict[str, Any]]:
    return [
        {
            "id": agent.slug,
            "name": agent.name,
            "role": agent.role,
            "domain": agent.domain,
            "capabilities": list(agent.capabilities),
            "input_fields": list(agent.input_fields),
            "kind": "task",
        }
        for agent in TASK_REGISTRY.values()
    ]
