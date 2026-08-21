"""Journava MCP server — expose the agent mesh as MCP tools.

Add this to Claude Desktop (or any MCP client) and say *"plan me a trip to
Chengdu"* — Journava's 21-agent mesh runs and returns the result. This is the
B2B "agentic travel infrastructure" surface: an agency's own agents, or Claude,
drive Journava directly.

Config (env):
  JOURNAVA_API       base URL incl. /api/v1  (default http://127.0.0.1:8401/api/v1)
  JOURNAVA_EMAIL     account email    (default admin@journava.test)
  JOURNAVA_PASSWORD  account password (default Journava!2026)

Run:  uv run --directory journava-mcp python server.py   (stdio)
"""

# NOTE: no `from __future__ import annotations` — FastMCP introspects real type
# objects to build tool schemas; stringized annotations break that.
import asyncio
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API = os.environ.get("JOURNAVA_API", "http://127.0.0.1:8401/api/v1").rstrip("/")
EMAIL = os.environ.get("JOURNAVA_EMAIL", "admin@journava.test")
PASSWORD = os.environ.get("JOURNAVA_PASSWORD", "Journava!2026")

mcp = FastMCP("journava")


async def _client() -> httpx.AsyncClient:
    """An authenticated client (logs in fresh, so the token is never stale)."""
    client = httpx.AsyncClient(base_url=API, timeout=90.0)
    resp = await client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    resp.raise_for_status()
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return client


@mcp.tool()
async def plan_trip(goal: str, origin: str = "", destination: str = "", scope: str = "full_trip") -> dict[str, Any]:
    """Run Journava's autonomous agents to plan/search a trip and wait for the result.

    goal: natural-language request (include dates/preferences).
    origin/destination: optional city or IATA code.
    scope: full_trip | flights_only | hotels | food | activities | getting_around
      | entry | itinerary_only | weather_risk | budget_check.
    Returns each agent's one-line summary.
    """
    async with await _client() as client:
        body: dict[str, Any] = {"goal": goal, "scope": scope}
        if origin:
            body["origin"] = origin
        if destination:
            body["destination"] = destination
        job = (await client.post("/jobs/plan", json=body)).json()
        job_id = job.get("id")
        for _ in range(90):
            rec = (await client.get(f"/jobs/{job_id}")).json()
            if rec.get("status") in ("done", "completed", "failed", "error"):
                results = (rec.get("result") or {}).get("results") or {}
                return {
                    "status": rec.get("status"),
                    "summaries": {
                        slug: r.get("summary")
                        for slug, r in results.items()
                        if isinstance(r, dict) and r.get("summary")
                    },
                }
            await asyncio.sleep(3)
        return {"status": "timeout", "job_id": job_id}


@mcp.tool()
async def get_active_trip() -> dict[str, Any]:
    """Return the traveller's current saved trip (or {"trip": null})."""
    async with await _client() as client:
        return (await client.get("/trip")).json()


@mcp.tool()
async def agency_overview() -> dict[str, Any]:
    """Agency view: managed trips and the OTA commission avoided by booking direct."""
    async with await _client() as client:
        return (await client.get("/agency/overview")).json()


if __name__ == "__main__":
    mcp.run()
