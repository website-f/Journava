"""AI travel assistant — a chat endpoint.

Answers any travel question with the LLM (streaming, and vision when an image is
attached), and can *launch Journava's autonomous agents* in the background when
the traveller asks for an actual search/plan. A launched run streams to the live
agent feed and lands in History/Trip when done, exactly like a Command Center
plan.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
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

_ANSWER_SYSTEM = """You are Journava's AI travel assistant. Answer any travel \
question helpfully, concisely and specifically — flights, hotels, halal food, \
visas, itineraries, local tips, safety, budgets. Use light markdown: **bold** the \
names and '- ' for bullet lists. If an image is attached, tell the traveller what's \
relevant (e.g. is this dish likely halal, what landmark is this and how to visit, \
what does this booking/document say)."""

_CLASSIFY_SYSTEM = """Classify the traveller's LATEST message. If they want to RUN \
an actual search / plan / comparison (flights, hotels, food, a whole trip, \
transport, visa, weather, budget, day itinerary), return an action; a plain \
question (e.g. "list halal restaurants", "do I need a visa?") is action = null.

Respond ONLY as JSON:
{"action": null OR {"run_scope": "full_trip|flights_only|hotels|food|activities|getting_around|entry|itinerary_only|weather_risk|budget_check", "goal": "one-line goal with any dates/prefs", "origin": "city/IATA or null", "destination": "city/country or null"}}"""

# Retained for a non-streaming fallback client: one structured call -> {reply, action}.
_SYSTEM = _CLASSIFY_SYSTEM.replace(
    '{"action":',
    'Also include a natural-language "reply". Respond ONLY as JSON:\n{"reply": "your message to show in chat", "action":',
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    # Optional data URL of an attached image (used for vision on the stream path).
    image: str | None = None


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _launch(action: dict[str, Any], user_id: str | None, messages: list[ChatMessage]) -> dict[str, Any] | None:
    """Launch a background plan job for a detected action. Returns the public job info or None."""
    run_scope = str(action.get("run_scope") or "").strip()
    if run_scope not in _RUNNABLE_SCOPES or not scopes.get(run_scope):
        return None
    last_user = next((m.content for m in reversed(messages) if m.role == "user"), "plan my trip")
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
        return {"type": "plan_started", "job_id": pub.get("id"), "scope": run_scope, "goal": job_body.goal}
    except Exception as exc:  # noqa: BLE001
        logger.warning("assistant could not launch job: %s", exc)
        return None


async def _classify(messages: list[ChatMessage]) -> dict[str, Any] | None:
    """Fast structured call: does the user want to launch a run? Returns the action or None."""
    convo: list[dict[str, Any]] = [{"role": "system", "content": _CLASSIFY_SYSTEM}]
    for m in messages[-8:]:
        convo.append({"role": m.role if m.role in ("user", "assistant") else "user", "content": m.content})
    try:
        resp = await llm.complete(convo, response_format={"type": "json_object"}, agent="assistant")
        data = json.loads(resp)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    action = data.get("action")
    return action if isinstance(action, dict) else None


def _answer_messages(body: ChatRequest) -> tuple[list[dict[str, Any]], str | None]:
    """Build answer messages, folding an attached image into the last user turn
    (multimodal) and selecting the vision model when one is present."""
    msgs: list[dict[str, Any]] = [{"role": "system", "content": _ANSWER_SYSTEM}]
    history = body.messages[-12:]
    last_user_idx = max((i for i, m in enumerate(history) if m.role == "user"), default=-1)
    for i, m in enumerate(history):
        role = m.role if m.role in ("user", "assistant") else "user"
        if body.image and i == last_user_idx:
            msgs.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": m.content or "What can you tell me about this image?"},
                        {"type": "image_url", "image_url": {"url": body.image}},
                    ],
                }
            )
        else:
            msgs.append({"role": role, "content": m.content})
    model = settings.llm_vision_model if body.image else None
    return msgs, model


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
    """Streaming chat: SSE frames {type: token|action|done}. Launches agents when
    the message is actionable; otherwise streams the answer token-by-token."""
    claims = getattr(request.state, "auth", {}) or {}
    user_id = claims.get("sub")

    async def gen() -> AsyncIterator[str]:
        action = await _classify(body.messages)
        if action:
            launched = _launch(action, user_id, body.messages)
            if launched:
                yield _sse({"type": "action", "action": launched})
                scope_label = str(launched.get("scope", "")).replace("_", " ")
                yield _sse(
                    {
                        "type": "token",
                        "content": (
                            f"Got it — I've started a **{scope_label}** search. It's running in "
                            "the background; I'll add the results to your History when it's done."
                        ),
                    }
                )
                yield _sse({"type": "done"})
                return

        msgs, model = _answer_messages(body)
        try:
            async for tok in llm.complete_stream(msgs, model=model, agent="assistant"):
                yield _sse({"type": "token", "content": tok})
        except Exception as exc:  # noqa: BLE001
            logger.warning("assistant stream failed: %s", exc)
            yield _sse({"type": "token", "content": "Sorry — I hit a snag. Try again?"})
        yield _sse({"type": "done"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat")
async def chat(body: ChatRequest, request: Request) -> dict[str, Any]:
    """Non-streaming fallback: one structured call → {reply, action}."""
    claims = getattr(request.state, "auth", {}) or {}
    user_id = claims.get("sub")

    convo: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM}]
    for m in body.messages[-12:]:
        convo.append({"role": m.role if m.role in ("user", "assistant") else "user", "content": m.content})
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
    launched = _launch(action, user_id, body.messages) if action else None
    return {"reply": reply, "action": launched}
