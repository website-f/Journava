"""AI travel assistant — a chat endpoint.

Answers any travel question with the LLM, and can *launch Journava's autonomous
agents* in the background when the traveller asks for an actual search/plan
(e.g. "find me a flight to Chengdu"). The launched run streams to the live agent
feed and lands in History/Trip when done, exactly like a Command Center plan.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core import llm
from app.core.settings import settings
from app.graph import scopes
from app.runtime import jobs
from app.runtime.router import PlanJobRequest, _run_plan_job

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/assistant", tags=["assistant"])

#: Scopes the assistant is allowed to launch from a chat request.
_RUNNABLE_SCOPES = {
    "full_trip",
    "flights_only",
    "hotels",
    "food",
    "activities",
    "getting_around",
    "entry",
    "itinerary_only",
    "weather_risk",
    "budget_check",
}

_SYSTEM = """You are Journava's AI travel assistant. Help with ANY travel question — \
flights, hotels, halal food, visas, itineraries, local tips, safety, budgets. Be \
friendly, concise and specific; format lists with clear names and one-line reasons.

You can also TRIGGER Journava's autonomous agents to run a REAL search in the \
background (they crawl live sources and book-quality APIs). When the user asks you \
to search / find / plan / compare something actionable, set "action".

Respond ONLY as strict JSON (no prose outside it):
{
  "reply": "the natural-language message to show in chat",
  "action": null OR {
    "run_scope": "full_trip | flights_only | hotels | food | activities | getting_around | entry | itinerary_only | weather_risk | budget_check",
    "goal": "a clear one-line goal capturing the request (include dates/prefs said)",
    "origin": "city or IATA, or null",
    "destination": "city or country, or null"
  }
}

Guidance:
- Pure question ("list halal restaurants in Chengdu", "do I need a visa for Japan?")
  → answer it well, action = null.
- Actionable search ("find flights KL to Chengdu on 5 Nov", "plan my Japan trip",
  "compare hotels in Bali") → set action with the best-matching run_scope, and make
  "reply" tell the user you've started it in the background and it'll appear in their
  History/Trip when done.
- Pick flights_only for flights, hotels for stays, food for restaurants, full_trip
  for a whole trip, getting_around for transport, entry for visas, weather_risk for
  weather/safety, itinerary_only for a day plan, budget_check for costs.
"""


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    # Optional data URL of an attached image (best-effort; noted to the model).
    image: str | None = None


@router.post("/chat")
async def chat(body: ChatRequest, request: Request) -> dict[str, Any]:
    claims = getattr(request.state, "auth", {}) or {}
    user_id = claims.get("sub")

    convo: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM}]
    for message in body.messages[-12:]:
        role = message.role if message.role in ("user", "assistant") else "user"
        convo.append({"role": role, "content": message.content})
    if body.image:
        convo.append(
            {
                "role": "user",
                "content": (
                    "[The user attached an image. If you cannot view it, ask them to "
                    "describe what they'd like to know about it.]"
                ),
            }
        )

    try:
        resp = await llm.complete(convo, response_format={"type": "json_object"}, agent="assistant")
        data = json.loads(resp)
        if not isinstance(data, dict):
            raise TypeError("assistant did not return an object")
    except Exception as exc:  # noqa: BLE001
        logger.warning("assistant chat failed: %s", exc)
        return {"reply": "Sorry — I hit a snag answering that. Mind trying again?", "action": None}

    reply = str(data.get("reply") or "").strip() or "How can I help with your trip?"
    action = data.get("action") if isinstance(data.get("action"), dict) else None

    launched: dict[str, Any] | None = None
    if action:
        run_scope = str(action.get("run_scope") or "").strip()
        if run_scope in _RUNNABLE_SCOPES and scopes.get(run_scope):
            last_user = next(
                (m.content for m in reversed(body.messages) if m.role == "user"), "plan my trip"
            )
            job_body = PlanJobRequest(
                goal=str(action.get("goal") or last_user),
                origin=(action.get("origin") or None),
                destination=(action.get("destination") or None),
                scope=run_scope,
            )
            try:
                job = jobs.launch(
                    "plan",
                    lambda: _run_plan_job(job_body, user_id),
                    meta={"scope": run_scope, "goal": job_body.goal},
                    user_id=user_id,
                )
                pub = jobs.public(job)
                launched = {
                    "type": "plan_started",
                    "job_id": pub.get("id"),
                    "scope": run_scope,
                    "goal": job_body.goal,
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("assistant could not launch job: %s", exc)

    return {"reply": reply, "action": launched}
