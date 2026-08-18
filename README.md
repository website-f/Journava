# Journava

> **Travel, run by agents.**

An autonomous multi-agent travel platform. A **Chief Agent** orchestrates
specialized AI agents — flights, hotels, research, budget, weather/risk — that
plan, verify, and continuously adapt an entire trip in real time. When a
disruption hits, the agents rebuild the itinerary autonomously instead of just
answering a prompt.

Built for the **Alibaba Cloud × Atlas Agentic AI Hackathon**, primarily with
Qoder. The full specification lives in [`JournavaPlan.md`](./JournavaPlan.md);
the working rules and evidence log live in [`.qoder/`](./.qoder/).

---

## Repo layout (spec §11)

```
journava/
├─ web/       Vite + React 19 PWA (design system, 6 surfaces)
├─ api/       FastAPI + LangGraph — supervisor + 21 agents + SSE stream
├─ skills/    atlas-flight-booking/  vendored Atlas skill → atlas-flight CLI
├─ gnosion/   memory brain, MCP mode (library mode runs inside api)
├─ camofox/   hardened-Firefox research service
├─ ops/       deploy.sh, Caddy snippet, .env.example
├─ docker-compose.yml   the one compose file
└─ JournavaPlan.md
```

## Architecture

**21 agents** in four phases. The Critic is a real barrier node, so a refinement
it triggers is visible to everything downstream:

```
chief ──► 8 core (flight · hotel · research · weather_risk ·
          │        visa · emergency · crowd · risk_advisory)
          ▼
      [ CRITIC ]  scores Tier 1, re-runs the weakest agent
          ▼
       9 enrichment (concierge · transport · sustainability · payment ·
          │           insurance · recommendation · analytics · language · shopping)
          ▼
     itinerary ──► budget ──► memory
```

Every agent runs **exactly once** per plan (plus an optional Critic retry).
`itinerary` precedes `budget` because budget aggregates the itinerary's items and
night count.

- **LangGraph supervisor** is the only executor when installed;
  `_run_without_langgraph` mirrors it exactly when it is not.
- **SSE agent stream** (`/api/v1/events`) drives the Agent Control Center and the
  live plan overlay — replay buffer + 15s heartbeat, in-process, no broker. The
  frontend holds **one** connection and shares it.
- **Gnosion** is the memory brain (our MIT IP): memory heads for facts,
  a classifier head for preference learning. `/health` reports which backend is
  live so a fallback store never passes as the real thing.
- **Preference scoping (§7.5):** preference present → narrow scope; absent →
  search globally. Flights are the exception — halal never filters flights, it
  adds an `MOML` meal code and nudges ranking.
- **Halal confidence is evidence-based.** The LLM's label is a hypothesis;
  `tools/halal.py` re-derives it from JAKIM / MUIS / HalalTrip. Claims are
  downgraded when nothing corroborates them, and never upgraded to `certified`
  without a certification body.

## Quick start (local dev)

```bash
# 1. backend  (boots with no credentials; /health reports what is live)
cd api
uv sync --extra brain        # --extra brain installs Gnosion; without it memory
uv run uvicorn app.main:app --reload --port 8400   # falls back in-process
# → http://localhost:8400/health   ·   docs at /docs

# 2. frontend
cd ../web
pnpm install
pnpm dev
# → http://localhost:5173
```

## Tests & checks

```bash
cd api && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
cd web && pnpm lint && pnpm build
```

The API suite runs fully offline — the LLM, every HTTP tool and the brain are
stubbed — because it asserts orchestration invariants (how many times an agent
runs, whether the parsed destination reaches it, which way money converts) rather
than third-party behaviour.

## Deploy (spec §13)

Behind the shared `/opt/reverse-proxy` (Caddy) — never a second TLS terminator.

```bash
cp ops/.env.example .env     # fill in POSTGRES_PASSWORD + the ⭐ keys
./ops/deploy.sh              # build, start, wait for /health, report degradation
```

Then append `ops/Caddyfile.journava.snippet` to the shared Caddyfile and reload.
`web` and `api` join the external `proxy` network, which is how Caddy resolves
them by name. See [`ops/README.md`](./ops/README.md).

Add `--profile full` to also start `gnosion` (MCP mode).

## Toolchain

| Layer   | Tools                                                                                        |
| ------- | -------------------------------------------------------------------------------------------- |
| web     | Vite 8, React 19, TypeScript 7, Tailwind v4, PWA, Radix, Framer Motion, React Flow, MapLibre |
| api     | Python 3.12, FastAPI, LangGraph, Pydantic v2, LiteLLM (Qwen hero + fallbacks), httpx, asyncpg |
| brain   | Gnosion (library + MCP)                                                                      |
| data    | PostgreSQL 16 · Redis 7                                                                      |
| package | pnpm (web) · uv (api)                                                                        |

MapLibre and React Flow are code-split out of the initial bundle — the PWA shell
is 574 KB (182 KB gzip) rather than 1.8 MB. Fonts are self-hosted in
`web/public/fonts` so the installed app renders offline.

## Status

All eight tracks are covered and the core loop is wired end to end: real
planning, real reconciliation, real disruption recovery, and a memory brain that
grows as it is used. Known gaps are the honest ones from §15 — the Atlas CLI must
be authenticated interactively before a demo, and hotel inventory is still
LLM-generated pending sandbox approval.
