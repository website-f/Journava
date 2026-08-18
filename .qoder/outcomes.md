# Qoder Outcomes — evidence log

Judging criterion "Qoder usage" (20%) rewards evidence. This is the running log:
what was asked, what changed, and how it was verified.

Keep entries append-only and specific. "Fixed the supervisor" is not evidence;
"36 agent invocations → 21, proven by a counting harness" is.

---

## 001 — Spec-vs-code audit

**Ask:** verify every claim in `JournavaPlan.md` against the implementation.

**Method:** read the 39KB spec, then all ~11.5k LOC; built throwaway harnesses to
measure behaviour rather than trusting the code's own comments.

**Found (measured, not inferred):**

| # | Defect | Evidence |
| - | ------ | -------- |
| 1 | Tier 2 ran 2× and Tier 3 ran 3× per plan | counting harness: 36 invocations, expected 21 |
| 2 | Chief's parsed destination reached no agent | research summary read `…for unknown` while chief parsed `Venice` |
| 3 | FX conversion inverted | `100 EUR → 20 MYR`, correct is `500` (25× understated) |
| 4 | Brain graph rendered 2 nodes / 0 edges | 8-node "demo graph" existed in `main.py` as dead code |
| 5 | Seeded profile silently dropped `halal` | seed used `dietary`, model wants `halal_required`; Pydantic ignores extras |
| 6 | Real Gnosion path would have crashed | `learn()` raises `KeyError` without `add_domain` — never exercised, dep wasn't installed |
| 7 | Recovery replayed the pre-disruption cache | same Redis key → identical "alternatives" → `RM0` was an artefact |
| 8 | `amadeus`/`youtube`/`reddit`/`halal` tools: 0 callers | 627 LOC unreachable |
| 9 | Outcome flywheel unwired | `record_outcome` defined twice, called never; UI thumbs were dead |
| 10 | Deploy used a compose file lacking the `proxy` network | Caddy could not resolve `web`/`api` |

## 002 — Remediation

**Ask:** fix and restructure.

**Changed:** Critic promoted to a real barrier node between tiers; single
executor; Tier 3 reordered to `itinerary → budget → memory`;
`apply_chief_enrichment` added; FX direction corrected; Gnosion driven properly
(memory heads for facts, classifier head for preferences) and added as the
`brain` extra; halal verification wired as a downgrade-only pass; Amadeus wired
as a second flight source; `verify_price` wired; outcome endpoints + UI added;
compose consolidated to one root file; SSE collapsed 4 connections → 1; bundle
split 1798KB → 574KB; fonts self-hosted; native `<select>` removed.

**Verified:**

```
api : 55 tests pass (pytest)      — invariants above are now regression-tested
web : tsc --noEmit clean, vite build clean
probe: 21 invocations, 0 duplicates; destination propagates; FX round-trips
brain: real Gnosion live, 1 → 9 memories across 8 domains after one plan
```

**Notes for the demo:** `/health` now names the memory backend, so a fallback is
visible instead of passing as the brain.

## 003 — Scoping, API Vault, dual-source flights, booking flow

**Ask:** diagnose an over-long answer, rebuild the Command Center around presets,
manage all provider keys in a vault with test-before-save, tag flight results by
source, add the Atlas purchase flow, and add a history page.

**Diagnosis (measured, not assumed):**

| Symptom | Actual cause |
| ------- | ------------ |
| "flights KLIA→BKI" answered with visa rules, embassy numbers, carbon estimates | no scoping — all 21 agents ran for every question |
| adding an LLM key "gave errors" | `.env` had three LLM keys, all empty; Engine had no test-before-save |
| answer said "KUL → unknown" | the Chief's parse needs an LLM; with none, no field resolved |
| a 3-agent run took 84s | dead Postgres re-dialled on *every* call (~4s each); an absent Ollama cost ~9s inside LiteLLM's retry loop |
| Atlas never returned inventory | the wrapper called a CLI surface that does not exist (`--from/--to`, a `--sandbox` flag) |

**Atlas correction.** Read the real CLI from the published wheel
(`atlas-flight-booking==0.3.12`). Actual surface: `--origin/--destination/--depart`,
`environment use sandbox` as persistent state, and a stable envelope
(`status/code/message/data`) with ~60 documented codes. Rewrote the wrapper and
the whole flow against it: search → `offer verify` → `booking confirm-price` →
`order create` (passengers via stdin) → `order pay` → `order status`.

**Built:** 10 planning scopes · API Vault (30 providers, Fernet-encrypted, 21
probes) · Engine rotation pool (health, local quota metering, cooldowns, reorder,
Ollama fallback) · dual-source flights tagged atlas/camofox/amadeus/llm with
source URLs · Atlas booking dialog enforcing the single-use payment rule ·
History (searches + bookings) · deterministic goal parser.

**Verified:**

```
flights_only:  21 agents → 3          (test_scopes asserts it for every scope)
latency:       84s → 27s cold → 5.9s warm
parse:         "klia to bki on 6th november night"
               → KUL, BKI, 2026-11-06, night window — with no LLM at all
api:           204 tests pass · ruff clean · 38 API routes
web:           tsc clean · build clean
```
