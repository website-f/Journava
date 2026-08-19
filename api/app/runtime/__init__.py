"""Generic agent runtime (Phase 2).

Journava started travel-shaped: the LangGraph supervisor plans a `TripRequest`
through a fixed roster. This package makes the platform domain-agnostic without
disturbing that flow:

- `tasks`   — a `TaskAgent` contract that takes a plain JSON payload (no trip),
  plus the first non-travel pack (email-replier). This is how you "hire" a new
  agent — add a TaskAgent, tag its capabilities, and it appears in the catalog.
- `catalog` — one capability manifest spanning the travel scopes AND the task
  agents, so the UI and the orchestrator discover agents by capability.
- `jobs`    — a background job manager. The Command Center dispatches work and
  returns immediately; progress streams over the existing SSE bus and the result
  is fetched by job id. That is what makes "your agents are working…" real.
"""
