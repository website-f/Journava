"""Agent Studio — plug-and-play role agents a business builds at runtime.

A hotel or travel agency describes a role in plain language ("a concierge that
answers guest questions and upsells room add-ons", "a lead qualifier for our
WhatsApp enquiries"). A meta-agent (the Architect) instantly drafts a deployable
agent — identity, system prompt, skills, and the tools it needs — and a generic
executor runs it against a task with the real LLM and, when the role calls for
it, a live Camofox web-research pass. No code, no config: describe → deploy → run.

This is deliberately data-driven (agents live in `custom_agents`, org-scoped)
rather than the code-registered `TaskAgent` pattern, so a non-technical operator
can spin up bespoke AI staff themselves.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth.deps import resolve_org_id
from app.core import db, llm
from app.core.settings import settings
from app.tools import discover

logger = logging.getLogger("journava")

router = APIRouter(prefix=f"{settings.api_prefix}/studio", tags=["studio"])

#: Tools the Architect may equip an agent with. Kept a closed set so a generated
#: agent only ever asks for capabilities the executor actually implements.
TOOLS: dict[str, str] = {
    "web_research": "Search & read the live web (Camofox) and cite sources",
    "competitor_watch": "Track competitor prices, offers and positioning on the web",
    "draft_document": "Write polished documents — proposals, itineraries, policies, replies",
    "customer_reply": "Answer a customer/guest message in the brand's voice",
    "package_planner": "Turn a client's wishes into a structured trip/stay package",
    "data_analysis": "Reason over numbers — occupancy, margins, lead quality",
}

_RESEARCH_TOOLS = {"web_research", "competitor_watch"}


class DesignRequest(BaseModel):
    role: str


class SaveRequest(BaseModel):
    name: str
    role: str
    tagline: str | None = None
    emoji: str | None = None
    system_prompt: str
    skills: list[str] = []
    tools: list[str] = []


class RunRequest(BaseModel):
    task: str


async def _org(request: Request) -> str:
    return await resolve_org_id(request)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    def _arr(v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except (ValueError, TypeError):
                return []
        return list(v) if isinstance(v, list) else []

    return {
        "id": str(row["id"]),
        "name": row["name"],
        "role": row["role"],
        "tagline": row.get("tagline"),
        "emoji": row.get("emoji") or "🤖",
        "system_prompt": row["system_prompt"],
        "skills": _arr(row.get("skills")),
        "tools": _arr(row.get("tools")),
        "runs": row.get("runs", 0),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


# --------------------------------------------------------------------------- #
# Design — the Architect drafts an agent from a plain-language role
# --------------------------------------------------------------------------- #

_ARCHITECT_SYSTEM = (
    "You are Journava's Agent Architect. Given a business role at a hotel or "
    "travel agency, design a ready-to-deploy AI agent for that business.\n"
    "Respond ONLY as JSON with exactly these keys:\n"
    '{"name": string (2-3 words, e.g. "Concierge Aria"),'
    ' "emoji": one emoji that fits the role,'
    ' "tagline": string (<= 8 words, what it does),'
    ' "system_prompt": string (2-4 sentences, written in the second person '
    '"You are ...", specific to travel/hospitality, action-oriented, tells the '
    "agent its job, tone, and boundaries),"
    ' "skills": array of 4-6 short skill phrases,'
    ' "tools": array — a SUBSET of these tool ids the role genuinely needs: '
    + ", ".join(TOOLS) + ".}"
)


@router.get("/tools")
async def list_tools() -> dict[str, Any]:
    """The palette of tools an agent can be equipped with."""
    return {"tools": [{"id": k, "description": v} for k, v in TOOLS.items()]}


@router.post("/design")
async def design_agent(body: DesignRequest, request: Request) -> dict[str, Any]:
    """Draft (but don't save) an agent from a role description."""
    role = body.role.strip()
    if len(role) < 3:
        raise HTTPException(status_code=400, detail="Describe the role in a bit more detail.")
    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": _ARCHITECT_SYSTEM},
                {"role": "user", "content": f"Role: {role}"},
            ],
            response_format={"type": "json_object"},
            agent="studio-architect",
        )
        draft = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent design failed: %s", exc)
        raise HTTPException(status_code=502, detail="The Architect couldn't draft this agent — try rephrasing the role.") from exc

    valid_tools = [t for t in (draft.get("tools") or []) if t in TOOLS]
    return {
        "draft": {
            "name": str(draft.get("name") or "New Agent")[:60],
            "emoji": str(draft.get("emoji") or "🤖")[:4],
            "tagline": str(draft.get("tagline") or "")[:80],
            "role": role,
            "system_prompt": str(draft.get("system_prompt") or ""),
            "skills": [str(s)[:60] for s in (draft.get("skills") or [])][:6],
            "tools": valid_tools or ["draft_document"],
        }
    }


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


@router.post("/agents")
async def create_agent(body: SaveRequest, request: Request) -> dict[str, Any]:
    org = await _org(request)
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    tools = [t for t in body.tools if t in TOOLS]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO custom_agents (org_id, name, role, tagline, emoji, system_prompt, skills, tools)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               RETURNING id, name, role, tagline, emoji, system_prompt, skills, tools, runs, created_at""",
            org,
            body.name[:60],
            body.role[:280],
            (body.tagline or "")[:80],
            (body.emoji or "🤖")[:4],
            body.system_prompt,
            json.dumps(body.skills[:8]),
            json.dumps(tools),
        )
    return {"agent": _public(dict(row))}


@router.get("/agents")
async def list_agents(request: Request) -> dict[str, Any]:
    org = await _org(request)
    pool = await db.get_pool()
    if pool is None:
        return {"agents": []}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, role, tagline, emoji, system_prompt, skills, tools, runs, created_at "
            "FROM custom_agents WHERE org_id = $1 ORDER BY created_at DESC",
            org,
        )
    return {"agents": [_public(dict(r)) for r in rows]}


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, request: Request) -> dict[str, bool]:
    org = await _org(request)
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM custom_agents WHERE id = $1 AND org_id = $2", uuid.UUID(agent_id), org
        )
    return {"removed": result.endswith("1")}


# --------------------------------------------------------------------------- #
# Run — the generic executor (shared by single-run and Agent Teams)
# --------------------------------------------------------------------------- #


async def _load_agent(org: str, agent_id: str) -> dict[str, Any] | None:
    pool = await db.get_pool()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, role, tagline, emoji, system_prompt, skills, tools, runs, created_at "
            "FROM custom_agents WHERE id = $1 AND org_id = $2",
            uuid.UUID(agent_id),
            org,
        )
    return _public(dict(row)) if row else None


async def _execute_agent(org: str, agent: dict[str, Any], task: str) -> dict[str, Any]:
    """Run one agent against a task: optional live web research + KB grounding,
    then the LLM under the agent's system prompt. Returns output + sources."""
    sources: list[str] = []
    research_block = ""
    used_research = False
    if any(t in _RESEARCH_TOOLS for t in agent["tools"]):
        try:
            found = await discover.crawl_sources([task], max_sources=6)
            if found.get("text"):
                used_research = True
                sources = found.get("sources") or []
                research_block = (
                    "\n\nLive web findings you may use (cite the sources when you rely on them):\n"
                    + found["text"][:6000]
                    + ("\n\nSources:\n" + "\n".join(sources) if sources else "")
                )
        except Exception as exc:  # noqa: BLE001
            logger.info("studio run research failed: %s", exc)

    kb_block = ""
    try:
        from app.kb import kb_context

        facts = await kb_context(org, task)
        if facts:
            kb_block = "\n\nYour business's own facts (use these; they override generic knowledge):\n" + facts
    except Exception as exc:  # noqa: BLE001
        logger.debug("kb inject failed: %s", exc)

    system = (
        agent["system_prompt"]
        + "\n\nYou are operating for the business as a deployed Journava agent. Be concrete "
        "and immediately useful; produce the actual deliverable (not a description of it). "
        "Plain text, no markdown headers." + kb_block + research_block
    )
    output = await llm.complete(
        [{"role": "system", "content": system}, {"role": "user", "content": task}],
        agent=f"studio:{agent['name'][:24]}",
    )
    try:
        pool = await db.get_pool()
        if pool is not None:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE custom_agents SET runs = runs + 1 WHERE id = $1", uuid.UUID(agent["id"]))
    except Exception:  # noqa: BLE001
        pass
    return {"output": output.strip(), "sources": sources, "used_research": used_research}


@router.post("/agents/{agent_id}/run")
async def run_agent(agent_id: str, body: RunRequest, request: Request) -> dict[str, Any]:
    """Run a saved agent against a task."""
    org = await _org(request)
    task = body.task.strip()
    if not task:
        raise HTTPException(status_code=400, detail="Give the agent a task.")
    agent = await _load_agent(org, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    try:
        result = await _execute_agent(org, agent, task)
    except Exception as exc:  # noqa: BLE001
        logger.warning("studio run failed: %s", exc)
        raise HTTPException(status_code=502, detail="The agent couldn't complete the task — try again.") from exc
    return {**result, "agent": {"name": agent["name"], "emoji": agent["emoji"]}}


# --------------------------------------------------------------------------- #
# Agent Teams — chain agents into an autonomous workflow (each hands off to next)
# --------------------------------------------------------------------------- #


class TeamRunRequest(BaseModel):
    agent_ids: list[str]
    brief: str


@router.post("/teams/run")
async def run_team(body: TeamRunRequest, request: Request) -> dict[str, Any]:
    """Run an ordered team: each agent works on the brief plus the previous
    agent's output, then hands off to the next — an autonomous back-office."""
    org = await _org(request)
    brief = body.brief.strip()
    if not brief or len(body.agent_ids) < 2:
        raise HTTPException(status_code=400, detail="Pick at least two agents and give the team a brief.")

    steps: list[dict[str, Any]] = []
    carry = ""
    for agent_id in body.agent_ids[:6]:
        agent = await _load_agent(org, agent_id)
        if agent is None:
            continue
        task = (
            f"Team brief: {brief}"
            + (f"\n\nThe previous teammate produced:\n{carry}\n\nBuild on it and do YOUR part." if carry else "\n\nYou are first — start the work.")
        )
        try:
            result = await _execute_agent(org, agent, task)
        except Exception as exc:  # noqa: BLE001
            logger.warning("team step failed (%s): %s", agent["name"], exc)
            steps.append({"agent": {"name": agent["name"], "emoji": agent["emoji"]}, "output": "", "ok": False})
            continue
        carry = result["output"]
        steps.append({
            "agent": {"name": agent["name"], "emoji": agent["emoji"]},
            "output": result["output"],
            "sources": result["sources"],
            "used_research": result["used_research"],
            "ok": True,
        })
    if not steps:
        raise HTTPException(status_code=404, detail="No valid agents in the team.")
    return {"steps": steps, "final": carry}
