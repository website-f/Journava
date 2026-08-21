"""AI travel assistant — a chat endpoint.

Answers any travel question with the LLM (streaming, and vision when an image is
attached), and can *launch Journava's autonomous agents* in the background when
the traveller asks for an actual search/plan. A launched run streams to the live
agent feed and lands in History/Trip when done, exactly like a Command Center
plan.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
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


class SocialRequest(BaseModel):
    #: A social-media URL (YouTube/TikTok/Instagram/X/Facebook/blog).
    url: str | None = None
    #: Pasted caption / post text (the most reliable input).
    text: str | None = None
    #: A screenshot of a post, as a data URL (read via the vision model).
    image: str | None = None
    scope: str = "full_trip"


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


# --------------------------------------------------------------------------- #
# Plan from a social-media post (any platform)                                #
# --------------------------------------------------------------------------- #


@router.post("/from-social")
async def from_social(body: SocialRequest, request: Request) -> dict[str, Any]:
    """Extract a trip seed from a post (URL / caption / screenshot) and launch a
    background plan for it. Returns the seed + the launched job."""
    from app.tools import social

    claims = getattr(request.state, "auth", {}) or {}
    user_id = claims.get("sub")

    seed = await social.extract_trip_seed(url=body.url, text=body.text, image=body.image)
    if seed.get("error"):
        return {"seed": None, "job": None, "error": seed["error"]}

    scope = body.scope if body.scope in _RUNNABLE_SCOPES else "full_trip"
    goal = seed.get("goal") or f"Plan a trip to {seed.get('destination')}"
    job_body = PlanJobRequest(
        goal=goal,
        origin=(seed.get("origin_hint") or None),
        destination=(seed.get("destination") or None),
        scope=scope,
    )
    try:
        job = jobs.launch(
            "plan",
            lambda: _run_plan_job(job_body, user_id),
            meta={"scope": scope, "goal": goal, "from_social": seed.get("source_kind")},
            user_id=user_id,
        )
        pub = jobs.public(job)
        return {
            "seed": seed,
            "job": {"id": pub.get("id"), "scope": scope, "goal": goal},
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("from-social launch failed: %s", exc)
        return {"seed": seed, "job": None, "error": "Couldn't start the plan — try again."}


# --------------------------------------------------------------------------- #
# Document upload (booking imports, corporate policy docs)                     #
# --------------------------------------------------------------------------- #

#: Cap uploads so a huge PDF can't OOM the worker or blow the LLM context.
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB
_MAX_LLM_CHARS = 12_000  # text sent to the summarizer
_MAX_RETURN_CHARS = 6_000  # text handed back for the next chat turn's context

_DOC_SYSTEM = """You are reading a document a traveller uploaded to a travel \
assistant. Classify it and pull out the travel-relevant facts.

kind:
- "booking": a flight/hotel/transport confirmation (dates, times, PNR/confirmation \
number, airline/hotel names, cities).
- "policy": a corporate/company travel policy (fare caps, cabin-class rules, \
preferred carriers/hotels, approval or per-diem rules).
- "itinerary": a day-by-day plan.
- "other": anything else.

Respond ONLY as JSON:
{"kind": "...", "summary": "2-4 sentence plain summary", "highlights": ["key fact", "..."]}"""


def _extract_text(filename: str, data: bytes) -> str:
    """Best-effort text extraction. Handles PDF (pypdf) and plain-text uploads."""
    name = (filename or "").lower()
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            parts = [(page.extract_text() or "") for page in reader.pages[:40]]
            return "\n".join(parts).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdf extract failed for %s: %s", filename, exc)
            return ""
    try:
        return data.decode("utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001
        return ""


async def _summarize_doc(text: str) -> dict[str, Any]:
    """Classify + summarize the extracted text. Degrades to a generic summary."""
    convo = [
        {"role": "system", "content": _DOC_SYSTEM},
        {"role": "user", "content": text[:_MAX_LLM_CHARS]},
    ]
    try:
        resp = await llm.complete(convo, response_format={"type": "json_object"}, agent="assistant")
        data = json.loads(resp)
        if not isinstance(data, dict):
            raise TypeError("doc summary not an object")
    except Exception as exc:  # noqa: BLE001
        logger.warning("doc summarize failed: %s", exc)
        return {"kind": "other", "summary": "", "highlights": []}
    kind = str(data.get("kind") or "other").strip().lower()
    if kind not in ("booking", "policy", "itinerary", "other"):
        kind = "other"
    highlights = [str(h) for h in data.get("highlights", []) if isinstance(h, (str, int, float))][:8]
    return {"kind": kind, "summary": str(data.get("summary") or "").strip(), "highlights": highlights}


@router.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    """Extract + summarize an uploaded document (PDF or text). Returns a summary
    and the (capped) extracted text, which the client attaches as context to the
    next chat turn. A "policy" doc is the seed for the corporate policy engine."""
    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        return {"error": "File too large (max 8 MB).", "filename": file.filename}
    text = _extract_text(file.filename or "upload", raw)
    if not text:
        return {
            "error": "Couldn't read any text from that file.",
            "filename": file.filename,
            "kind": "other",
        }
    summary = await _summarize_doc(text)

    # A corporate policy doc closes the loop: extract the structured constraints
    # and save them as the org's active policy, so the next flight/hotel search
    # already respects it (Phase 2.3).
    policy_saved = False
    if summary.get("kind") == "policy":
        try:
            from app.auth.deps import resolve_org_id
            from app.brain import policy_store
            from app.tools import policy as policy_tools

            org_id = await resolve_org_id(request)
            extracted = await policy_tools.extract_from_text(text)
            await policy_store.save_policy(org_id, extracted)
            policy_saved = True
        except Exception as exc:  # noqa: BLE001 — best-effort; the summary still returns
            logger.warning("policy auto-save failed: %s", exc)

    return {
        "filename": file.filename,
        "chars": len(text),
        "text": text[:_MAX_RETURN_CHARS],
        "policy_saved": policy_saved,
        **summary,
    }
