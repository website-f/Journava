# Journava

> **Travel, run by agents.**

An autonomous multi-agent travel platform. A **Chief Agent** orchestrates
specialized AI agents — flights, hotels, research, budget, weather/risk — that
plan, verify, and continuously adapt an entire trip in real time. When a
disruption hits, the agents rebuild the itinerary autonomously instead of just
answering a prompt.

Built for the **Alibaba Cloud × Atlas Agentic AI Hackathon**, primarily with
Qoder. The full specification lives in [`JournavaPlan.md`](./JournavaPlan.md).

---

## Repo layout (spec §11)

```
journava/
├─ web/       Vite + React 19 PWA (design system, 5 surfaces)
├─ api/       FastAPI + LangGraph — orchestrator + 8 agents + SSE stream
├─ skills/    atlas-flight-booking/  vendored Atlas skill → atlas-flight CLI
├─ gnosion/   memory brain (library in-process + MCP service)   [Phase 2]
├─ camofox/   hardened-Firefox research service                 [Phase 2]
├─ ops/       docker-compose, .env.example, deploy.sh, Caddy snippet
└─ JournavaPlan.md
```

## Architecture at a glance

- **8 MVP agents** (spec ships these; pitches 20): `chief · flight · hotel ·
  research · weather_risk · budget · itinerary · memory`.
- **LangGraph supervisor** fans the parallel agents out, then runs budget →
  itinerary → memory in sequence. Falls back to `asyncio.gather` when LangGraph
  is absent.
- **SSE agent stream** (`/api/v1/events`) drives the Agent Control Center — a
  replay buffer + 15s heartbeat, in-process, no broker.
- **Gnosion** is the memory brain (our MIT IP): library mode on the hot path,
  MCP mode for the brain graph.
- **Preference scoping (§7.5):** preference present → narrow scope; absent →
  search globally. Flights are the exception — halal never filters flights, it
  adds an `MOML` meal code and nudges ranking.
- **Halal confidence** is always labelled: `certified | muslim_friendly |
  unverified` — never claim "certified" without a certification source.

## Quick start (local dev)

```bash
# 1. backend  (no credentials needed to boot; /health reports what's live)
cd api
uv sync
uv run uvicorn app.main:app --reload --port 8400
# → http://localhost:8400/health

# 2. frontend
cd ../web
pnpm install
pnpm dev
# → http://localhost:5173
```

## Deploy (spec §13)

Behind the shared `/opt/reverse-proxy` (Caddy) — never a second TLS terminator.

```bash
cd ops
cp .env.example .env        # fill in POSTGRES_PASSWORD + the ⭐ keys
./deploy.sh                 # build + up + health check
# then register the domain: append ops/Caddyfile.journava.snippet to the proxy
```

Add `--full` to also start the `gnosion` and `camofox` services (Phase 2).

## Toolchain

| Layer    | Tools                                                      |
| -------- | --------------------------------------------------------- |
| web      | Vite 8, React 19, TypeScript 7, Tailwind v4, PWA, Radix, Framer Motion, React Flow, MapLibre |
| api      | Python 3.12, FastAPI, LangGraph, Pydantic v2, LiteLLM (Qwen hero + fallbacks), httpx, asyncpg, redis |
| data     | PostgreSQL 16 · Redis 7                                    |
| package  | pnpm (web) · uv (api)                                      |

## Status

**Phase 0 — Scaffold** (this repo): repo structure, compose, DB schema, health
checks, the full §10 design system, and all Phase-0 backend contracts. Later
phases wire the real tools, the reflexion loop, the disruption recovery, and the
Qoder Outcomes evidence — see the roadmap in [`JournavaPlan.md`](./JournavaPlan.md) §12.
