# Journava API

FastAPI + LangGraph backend. Hosts the orchestrator, the 8 MVP agents, the SSE
agent-event stream, and the Gnosion brain client.

## Layout

```
app/
├─ agents/   chief · flight · hotel · research · weather_risk · budget · itinerary · memory
├─ tools/    atlas_skill, open_meteo (reference shape for every later tool)
├─ brain/    gnosion_client.py — library mode on the hot path, MCP optional
├─ graph/    langgraph supervisor + edges
├─ core/     settings · llm (litellm) · cache (redis) · db (asyncpg) · sse
├─ db/       schema.sql (idempotent, applied on boot)
└─ main.py   FastAPI app
```

## Run locally

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8400
```

No credentials required to boot. Postgres, Redis, Gnosion and the model keys are
all optional — each degrades gracefully and `/health` reports which are live:

```bash
curl http://localhost:8400/health
```

## Endpoints

| Method | Path                  | Purpose                                    |
| ------ | --------------------- | ------------------------------------------ |
| GET    | `/health`             | liveness + dependency report (always 200)  |
| GET    | `/api/v1/events`      | SSE agent-event stream (replay + heartbeat) |
| GET    | `/api/v1/agents`      | agent roster for the control center        |
| POST   | `/api/v1/plan`        | run one planning pass across the graph     |
| GET    | `/api/v1/profile`     | standing traveler preferences              |
| POST   | `/api/v1/profile`     | persist preferences into Gnosion           |

## Preference scoping (spec §7.5)

The rule every agent obeys: **preference present → narrow the scope; preference
absent → search globally.** Flights are the explicit exception — `halal_required`
is never a filter there, it becomes an `MOML` meal code at booking time and only
nudges ranking.

## Tests

```bash
uv run pytest
uv run ruff check .
```
