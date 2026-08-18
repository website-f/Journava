# Journava — Master Build Spec

> **Journava** — *Travel, run by agents.*
> An autonomous multi-agent travel intelligence that **plans, researches, books, and adapts** your entire journey in real time. When something changes, your agents don't just notify you — they solve it.

**Hackathon:** Alibaba Cloud × Atlas Agentic AI Hackathon
**Category (our "ninth answer"):** A single agentic platform that unifies all eight tracks under one orchestration + memory layer.
**Hosting:** Self-hosted on VPS via Docker, behind the shared `/opt/reverse-proxy` (Caddy).

---

## Table of Contents

1. [Vision & Positioning](#1-vision--positioning)
2. [Hackathon Fit (track + criteria coverage)](#2-hackathon-fit)
3. [Product Experience (the 5 surfaces)](#3-product-experience)
4. [Agent Roster — 20 vision / 8 MVP](#4-agent-roster)
5. [System Architecture](#5-system-architecture)
6. [Tech Stack](#6-tech-stack)
7. [Memory & Self-Improvement (Gnosion + Reflexion)](#7-memory--self-improvement)
   - [7.5 Personalization & Preference Scoping](#75-personalization--preference-scoping)
8. [Camofox — human-like research + API fusion](#8-camofox--human-like-research--api-fusion)
9. [Free API & Tools List (with key links)](#9-free-api--tools-list)
10. [UI / UX Design System](#10-ui--ux-design-system)
11. [Repo Structure & Docker Layout](#11-repo-structure--docker-layout)
12. [Implementation Roadmap](#12-implementation-roadmap)
13. [Deployment (VPS + Caddy)](#13-deployment)
14. [Demo & Submission Plan](#14-demo--submission-plan)
15. [Honest Risks & Caveats](#15-honest-risks--caveats)

---

## 1. Vision & Positioning

Most hackathon entries will be "an AI trip planner." Journava is deliberately different: **an event-driven, multi-agent system with long-term memory that gets smarter every trip.**

| | Chatbot travel app | **Journava** |
|---|---|---|
| Model | User asks → LLM answers | Monitor → reason → collaborate → negotiate → execute → learn |
| Agents | One | A Chief Agent orchestrating 6–8 specialists (extensible to 20) |
| Memory | Forgets each session | Persistent, **self-improving** brain (Gnosion) |
| Data | One API | APIs (truth) + browser research (discovery) + verification |
| Behaviour | Reactive | **Proactive** — solves disruptions autonomously |

- **One-liner:** *An autonomous network of AI agents that plans, monitors, optimizes, and adapts your entire journey in real time.*
- **Killer feature:** *When something changes, your agents don't notify you — they solve it.*
- **Long-term vision:** a programmable OS where travelers and travel businesses deploy specialized agents that collaborate across the whole ecosystem.

---

## 2. Hackathon Fit

### Track coverage (all 8)

| Track | Covered by |
|---|---|
| 01 Hotels & Accommodations | Hotel, Concierge |
| 02 Flights & Aviation | Flight, Transport, Emergency, Visa |
| 03 Attractions & Destinations | Destination, Crowd, Weather |
| 04 Activities & Experiences | Activity, Recommendation, Concierge |
| 05 Payments & Fintech | Payment, Budget, Insurance |
| 06 Data & Analytics | Analytics, Memory, Research |
| 07 AI Agent Ecosystem | **Chief/Orchestrator, Risk & Verification** |
| 08 Other Innovations | Sustainability, Research (generative content) |

### Judging criteria → how we win

| Criterion | Weight | Our play |
|---|---|---|
| Innovation | 30% | Multi-agent orchestration + **self-improving memory** + live disruption recovery ("money shot") |
| Feasibility | 30% | Ship **6–8 real agents**, flawless orchestration, plug-in architecture for the rest |
| Qoder usage | 20% | Qoder = **hero dev tool**; keep evidence (`.qoder/rules`, commits, screen recording, Outcomes) |
| Demo | 20% | Live agent-activity UI + Gnosion brain graph growing on screen |

---

## 3. Product Experience

The whole product is **one conversation + one travel workspace**. The user never manages individual agents. Five surfaces:

### 3.1 🏠 Command Center (home)
One universal input: *"Plan a 7-day Venice trip for 2, budget RM8,000, we love food + culture, avoid crowds, max 1 connection."*
- Multimodal input: text, 🎤 voice, 📎 file, 📷 image, 🎥 video ("make my trip feel like this").
- Quick actions: Flights · Hotels · Explore · Budget · Trips.
- Active-trip card with live budget progress.

### 3.2 🧠 Research Board
Agents produce a **destination intelligence board**, not a chat blob:
- Flights (best value / comfort / schedule), Hotels (shortlist w/ reasons), Experiences, Traveler Intelligence (Google + YouTube + Reddit + weather), each with **"Why did Journava choose this?"** explainability.
- **Social Signal** score (clearly labelled *Journava-derived*, not objective) + contradiction detection ("popular, but recent Reddit complaints about midday queues").

### 3.3 🧳 My Trip
Day-by-day itinerary, budget, bookings, maps, tickets, documents. Agents remain active after booking → proactive alerts + one-tap recovery plans.

### 3.4 🤖 Agent Control Center (transparency + demo)
Live status of each agent (ACTIVE / WORKING / MONITORING / WAITING) + an **event stream**. This is what proves "multiple agents collaborating" to judges.

### 3.5 👤 Profile & Preferences
A dedicated profile page where the traveler sets **standing preferences once**; agents read them to **narrow scope**, and fall back to **global search when a preference is absent**.
- **Dietary — Halal (required)** for Muslim travelers → restaurants/activities filtered to halal-certified / Muslim-friendly with a confidence label; a **halal special-meal (MOML)** request is attached to flight bookings. Also allergies, veg/vegan.
- Cuisine likes/dislikes · budget defaults · pace · interests (culture/food/nature) · hotel prefs (near transit, family room) · seat + timing (no red-eye, ≤1 connection) · accessibility/mobility · language · home airport · loyalty programs · companions.
- Saved to **Gnosion** as the seed of long-term memory → every agent recalls it and it self-improves from accepted/rejected choices.
- Scoping is **per-domain** (see §7.5). Key rule the user set: **flights stay global** — personalization affects ranking + the meal request, never flight availability.

### The "wow" flow
Plan trip → agents light up → itinerary built → **simulate flight disruption** → agents cascade (Flight → Risk → Hotel → Transport → Budget → Activity → Chief) → **"Recovery Plan Ready — additional cost RM0"** → Accept.

---

## 4. Agent Roster

### Build these 8 for real (the MVP)
1. **Chief Agent** — orchestration, delegation, reconciliation (LangGraph supervisor).
2. **Flight Agent** — wraps the official **Atlas Flight Booking Skill** (live search → price-verify → baggage/seat → order → Atlas-balance pay → ticketing) + Amadeus for breadth; ranks, handles disruption/rebook. Runs in **sandbox** (key acquired). Flights stay **global** (see §7.5).
3. **Hotel Agent** — sandbox APIs + research; compare, auto-switch.
4. **Research/Travel-Intelligence Agent** — Camofox + YouTube/Reddit; sentiment, popularity, contradictions.
5. **Weather/Risk Agent** — Open-Meteo + GDELT; triggers replanning.
6. **Budget Agent** — cost tracking + FX; keep trip in budget.
7. **Itinerary Agent** — day-by-day plan assembly.
8. **Memory Agent** — Gnosion read/write; loads the **Traveler Profile** (§3.5 / §7.5), preferences + outcomes (self-improvement).

### Vision layer (plug-in later, shown in architecture)
Visa · Transport/Multi-modal · Emergency · Concierge · Insurance · Payment · Sustainability · Crowd · Recommendation · Analytics · Language · Shopping.

> Positioning: pitch **20 as the platform vision**, demo **8 that genuinely work**. Adding an agent = adding a LangGraph node + a tool. That's the "extensible ecosystem" story for track 07.

---

## 5. System Architecture

Two-tier for the MVP (not microservices) — fewer moving parts, faster to a flawless demo. The plug-in architecture is preserved *inside* the agent layer.

```
                    shared /opt/reverse-proxy (Caddy · TLS)
                                   │
                 ┌─────────────────┴──────────────────┐
                 ▼                                     ▼
        Vite React PWA  ───SSE / REST───►     FastAPI backend
        (shadcn UI,                            │  LangGraph orchestrator
         React Flow graph,                     │   ├─ Chief Agent (supervisor)
         SSE live stream)                      │   ├─ Flight / Hotel / Research …
                                               │   ├─ Critic / Reflexion loop
                                               │   └─ LiteLLM ─► Qwen / Gemini / Groq
                                               │
              ┌────────────────────────────────┼───────────────────────────┐
              ▼                                 ▼                           ▼
        Gnosion brain                       PostgreSQL                    Redis
   (semantic memory, KG,               (trips, bookings,           (cache, pub/sub bus,
    self-improving, MCP,                 users, itineraries)         sessions, job queue)
    d3 viz — lib + MCP)
              │
              ▼
        Camofox service  ──►  human-like public web research
        Atlas Flight Booking Skill (search→verify→book→pay→ticket) · APIs (Amadeus, Open-Meteo, YouTube, Reddit, GDELT…)
```

### Core data flow — the reconciliation pattern (reused for flights, hotels, activities)
```
User goal → Chief Agent
   ├── (parallel) Structured Agent → Atlas/Amadeus → machine-readable inventory
   └── (parallel) Research Agent   → Camofox → public offers / reviews
          ↓
   Verification Agent → same itinerary? (route·date·stops·fare class·baggage·taxes·currency)
          ↓
   Ranking Agent → Cheapest advertised │ Cheapest w/ baggage │ Best value │ Best time
          ↓
   Result + real booking link + "why?" + "last checked 2 min ago"
```
Rules: **API = source of truth for structure; crawl = discovery + verification.** Never surface a crawled price without verification. Cache aggressively (Redis TTL 6–24h) to protect free quotas. Before acting, every agent reads the **Traveler Profile** (§7.5): a relevant preference **narrows scope** (e.g. halal-only restaurants); its absence means **global search**.

---

## 6. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| **Frontend** | **Vite + React 19 + TypeScript** | SPA PWA, no SSR → FastAPI is the only backend |
| PWA | **vite-plugin-pwa** (Workbox) | Installable, offline shell, add-to-home-screen |
| UI kit | **shadcn/ui** (Radix primitives) + **Tailwind CSS** | All components custom-styled (no native controls) |
| Animation | **Framer Motion** | Agent nodes, transitions, the "wow" cascade |
| Agent viz | **React Flow** | Live agent graph |
| Maps | **MapLibre GL** + MapTiler/OSM tiles | Free, no billing card |
| Data fetching | **TanStack Query** + **SSE** client | Live agent progress streaming |
| Toasts | **Sonner** | Replaces `alert()` (see §10) |
| **Backend** | **Python 3.12 + FastAPI** | Hosts orchestrator + agents |
| Orchestration | **LangGraph** | Supervisor + specialist nodes, streaming, checkpoints |
| Schemas | **Pydantic v2** | Structured agent I/O |
| LLM gateway | **LiteLLM** | Swap models without code changes |
| Hero model | **Alibaba Qwen** (DashScope) + Gemini/Groq fallback | Strengthens Alibaba story |
| **Brain** | **Gnosion** (library **+** MCP) | Semantic memory, self-improvement, KG, d3 viz |
| Self-improve | Reflexion/Critic loop · DSPy (optional, offline) | Runtime correction + prompt optimization |
| **Browser** | **Camofox** (own container) | Human-like public research |
| HTTP | **httpx** (async) | Parallel API fan-out |
| **Flight booking** | **Atlas Flight Booking Skill** (Apache-2.0) | Official search→verify→book→pay→ticket; wraps `atlas-flight` CLI (stable JSON, response codes); **sandbox** mode |
| **Data** | **PostgreSQL 16** + **Redis 7** | Qdrant dropped — Gnosion covers semantic memory |
| Auth | **Better Auth** (or FastAPI JWT) | Keep light for hackathon |
| **Edge** | shared **Caddy** (`/opt/reverse-proxy`) | No second TLS terminator |
| Dev | **Qoder** (hero) + Claude Code / Codex | Qoder drives the 20% |
| Tooling | **uv** (Python), **pnpm** (frontend), GitHub, Docker Compose | |

**Compose services (6):** `web · api · gnosion · camofox · postgres · redis`.

---

## 7. Memory & Self-Improvement

Three layers on top of LangGraph make Journava beat a plain agent:

### ① Gnosion — long-term semantic memory + self-improvement
- **Memory heads** (embedding→value, k-NN recall): agents store experiences/decisions/outcomes and recall next time → **Memory Agent**.
- **Champion/challenger classifiers**: learns preferences (window seat, no red-eye, avoid crowds) and improves **without regression** → **Recommendation Agent** getting smarter each trip.
- **Knowledge-graph mapping**: destinations, reviews, POIs as typed nodes for semantic recall.
- **d3 neuro-graph** (`gns ui`): show the brain growing live during the demo.
- Runs **both modes**:
  - **Library** — imported into FastAPI for hot-path memory (`from gnosion import Gnosion`).
  - **MCP server** (`gns mcp`) — shared memory for the agents at runtime + for Qoder/Claude Code during dev.
- It's **your own MIT IP (Crave Asia)** → zero licensing risk + a genuine differentiator.

```python
# api/brain/gnosion_client.py  (library mode, hot path)
from gnosion import Gnosion

brain = Gnosion.load("data/journava.gnosion") if exists else Gnosion()

def remember(domain: str, key: str, value: str, label: str | None = None):
    brain.learn(domain, key, label=label, value=value)
    brain.export("data/journava.gnosion")   # or debounce/consolidate

def recall(domain: str, query: str):
    return brain.predict(domain, query)      # k-NN recall + confidence
```
```
# MCP mode (agents + dev tools share the same brain)
gns mcp --brain data/journava.gnosion
```

### ② Reflexion / Critic loop — runtime self-correction
After an agent answers, a Critic scores it vs. the goal; if weak, it retries **with the critique**. The Verification Agent already does this for flights — generalize it to hotels/activities.

### ③ Outcome learning — the flywheel
Accepted vs. rejected recommendations are written back to Gnosion → the next plan starts smarter. (Optional advanced: **DSPy** to auto-optimize agent prompts against a rubric offline — pairs with Qoder "Outcomes.")

---

## 7.5 Personalization & Preference Scoping

The **Traveler Profile** (§3.5) is Journava's personalization layer. Rule of thumb:

> **Preference present → narrow the scope. Preference absent → search globally.**

The profile is stored in **Gnosion** (seeds long-term memory; self-improves from choices). Before acting, each agent reads it and decides whether a preference is a **hard filter**, a **soft ranking signal**, or **not applicable** for its domain.

### Preference scoping matrix
| Preference | Restaurants / Food | Activities | Hotels | **Flights** |
|---|---|---|---|---|
| **Halal (required)** | **Hard filter** — certified / Muslim-friendly only, with confidence label | **Hard filter** (halal food nearby) | Soft (halal breakfast option) | **Global** — never filtered; attach **halal meal code (MOML)** to booking |
| Cuisine likes (ramen, seafood…) | Soft ranking | Soft | — | — |
| Allergies | **Hard filter / warn** | Warn | Soft | Special-meal note |
| Budget | Soft cap | Soft | Soft cap | Soft cap (ranking) |
| No red-eye / ≤1 connection | — | — | — | **Soft filter / ranking** (timing only; inventory stays global) |
| Near public transport | — | Soft | Soft ranking | — |
| Accessibility / mobility | Hard where needed | Hard where needed | **Hard filter** | Assistance request |
| Interests (culture/food/nature) | — | Soft ranking | — | — |

**Key rule the user set:** flights **always** reference the global inventory. Personal/dietary prefs never remove flight options — they only (a) influence ranking (timing, connections, budget) and (b) add booking-time requests (e.g. **MOML** halal meal).

### Halal verification (a real differentiator)
Halal isn't a clean API flag, so the **Research Agent** cross-checks sources and labels confidence:
- **Certified** — listed by a certification body (MY **JAKIM**, SG **MUIS**, ID **MUI**) or a verified directory.
- **Muslim-friendly** — strong signals (HalalTrip / Zabihah, reviews mention halal) but no formal cert.
- **Unverified** — surfaced with a clear ⚠️ label; never claimed as certified without evidence.

This makes Journava genuinely useful for Muslim travelers (a large SEA/Gulf market) and is an honest, standout personalization story for the judges.

### No-profile fallback
If the profile (or a given field) is empty, agents **search globally** and may ask **one** targeted question ("Any dietary needs?") rather than guessing — the answer is written back to the profile for next time.

---

## 8. Camofox — human-like research + API fusion

Camofox wraps **Camoufox** (hardened Firefox) as an automation server for AI agents. Firefox-based = it doesn't leak the Chrome DevTools Protocol fingerprints that flag Playwright-Chromium.

### Browsing like a human (anti-detection, defensible use)
1. Use Camoufox's **consistent** fingerprint spoofing (canvas/WebGL/fonts/screen). Consistency beats randomness.
2. **Match locale + timezone + geo** to the proxy exit IP.
3. **Human timing**: randomized think-time (800–3500 ms), per-keystroke jitter (not `fill()`).
4. **Human motion**: Bézier-curve mouse moves, hover before click, gradual scroll (triggers lazy-load).
5. **Real viewport**, non-headless-detectable render.
6. **Session isolation + rotating/residential proxies** per research job.
7. **Throttle & respect**: low concurrency, honor `robots.txt`, back off on 429s.
8. **Official API first, permitted public pages second, never bypass logins/paywalls/captcha.**

> Frame it as a **Browser Research Agent**, not a "bot-detection bypass." Rule: *Official API → permitted public research → never bypass access controls.*

### Fusion (parallel API + crawl) — see the reconciliation diagram in §5
Structured APIs give reliable inventory; Camofox expands discovery + verifies; the Verification/Ranking agents reconcile; the Chief Agent decides.

---

## 9. Free API & Tools List

Legend — **Key?**: 🔓 none · 🔑 key/signup · 🏦 billing card (free monthly cap) · 🤝 partner/sandbox approval.

> Reality check: "free, no limit" barely exists. Build on the 🔓 open ones, use 🔑 free tiers within quota + **cache hard**, and let Camofox fill gaps.

### ✈️ Flights
| Provider | Use | Key? | Get it |
|---|---|---|---|
| **Atlas Flight Booking Skill** ⭐ | Core: search→verify→book→pay→ticket (Apache-2.0) | 🔑 (sandbox key ✓) | https://github.com/atlas-doc/atlas-flight-booking-skill |
| **Amadeus Self-Service** | Search / cheapest dates (test env) | 🔑 | https://developers.amadeus.com/register |
| **AviationStack** | Flight status | 🔑 | https://aviationstack.com/signup/free |
| **OpenSky Network** | Live positions (free) | 🔓/🔑 | https://opensky-network.org/ |

**Add the Atlas skill** (also usable inside Qoder/Claude Code during dev):
```bash
npx --yes skills add https://github.com/atlas-doc/atlas-flight-booking-skill --skill atlas-flight-booking
# auto-installs the `atlas-flight` CLI (v0.3.12); run in sandbox; auth once via browser OAuth (stored in OS keychain)
```
The Flight Agent's `atlas_skill` tool shells out to the `atlas-flight` CLI and branches on its stable JSON response codes.

### 🏨 Hotels
| Provider | Use | Key? | Get it |
|---|---|---|---|
| **Hotelbeds APItude** | B2B inventory (sandbox) | 🤝 | https://developer.hotelbeds.com/ |
| **Expedia Rapid** | Hotels (sandbox) | 🤝 | https://developers.expediagroup.com/rapid |
| **Booking.com** | Hotels | 🤝 | https://developers.booking.com/ |

### 🍜 Places / Restaurants / Attractions
| Provider | Use | Key? | Get it |
|---|---|---|---|
| **Google Places (New)** | Ratings, reviews, photos | 🏦 | https://console.cloud.google.com/ |
| **Foursquare Places** | POIs | 🔑 | https://foursquare.com/developers/ |
| **Yelp Fusion** | Reviews/ratings | 🔑 | https://docs.developer.yelp.com/ |
| **OpenTripMap** | Attractions + descriptions | 🔑 (free) | https://opentripmap.io/product |
| **Geoapify** | Geocoding/POI/routing | 🔑 (free) | https://www.geoapify.com/ |
| **OSM Overpass** | POIs by area | 🔓 | https://overpass-api.de/ |
| **Nominatim** | Geocoding | 🔓 (fair-use) | https://nominatim.org/ |

### 🕌 Dietary / Halal (mostly Research Agent + crawl)
| Provider | Use | Key? | Get it |
|---|---|---|---|
| **HalalTrip** | Halal restaurants, prayer times | 🔑 | https://www.halaltrip.com/ |
| **Zabihah** | Halal directory (public) | 🔓 (crawl) | https://www.zabihah.com/ |
| **JAKIM (MY) / MUIS (SG)** | Halal certification lookup | 🔓 (public) | https://www.halal.gov.my/ · https://www.muis.gov.sg/ |

### 🗺️ Maps / Tiles
| **MapTiler** | Map tiles for MapLibre | 🔑 (free) | https://www.maptiler.com/ |
| **Mapbox** | Maps/routing | 🔑 (free tier) | https://account.mapbox.com/ |
| **OpenStreetMap** | Base data | 🔓 | https://www.openstreetmap.org/ |

### 🌦️ Weather
| **Open-Meteo** ⭐ | Forecast (no key, generous) | 🔓 | https://open-meteo.com/ |
| **OpenWeatherMap** | Backup | 🔑 | https://openweathermap.org/api |
| **WeatherAPI** | Backup | 🔑 | https://www.weatherapi.com/ |

### 💱 Currency · 🌍 Country
| **Frankfurter** ⭐ | FX rates (no key) | 🔓 | https://frankfurter.dev/ |
| **exchangerate.host** | FX | 🔑 (free) | https://exchangerate.host/ |
| **REST Countries** | Country/currency/lang | 🔓 | https://restcountries.com/ |

### 🚖 Transport / Routing
| **OpenRouteService** | Routing/isochrones | 🔑 (free) | https://openrouteservice.org/dev/#/signup |
| **OSRM** | Routing (public/self-host) | 🔓 | https://project-osrm.org/ |

### 📺 Video · 💬 Social · 📰 News
| **YouTube Data API** | Video search + stats (10k units/day) | 🔑/🏦 | https://console.cloud.google.com/ |
| **Reddit API** | Traveler sentiment | 🔑 | https://www.reddit.com/prefs/apps |
| **GDELT** ⭐ | Global events/news (free) | 🔓 | https://www.gdeltproject.org/ |
| **NewsAPI** | News (backup) | 🔑 | https://newsapi.org/register |

### 🧠 AI Search / Extraction
| **Tavily** | AI search | 🔑 (free) | https://tavily.com/ |
| **Firecrawl** | Web→Markdown | 🔑 (free) | https://www.firecrawl.dev/ |
| **Jina Reader** | Clean page text | 🔓 (basic) | https://jina.ai/reader/ |

### 🏛️ Visa · 📷 Images · 📧 Email · 💰 Payments
| **Sherpa** | Entry requirements | 🤝 | https://www.joinsherpa.com/travel-restrictions-api |
| **Unsplash** | Destination imagery | 🔑 (free) | https://unsplash.com/developers |
| **Pexels** | Imagery/video | 🔑 (free) | https://www.pexels.com/api/ |
| **Resend** | Transactional email | 🔑 (free) | https://resend.com/ |
| **Stripe** | Payments (test) | 🔑 | https://dashboard.stripe.com/register |

### 📚 Content · 🤖 LLM · 🌐 Browser
| **Wikivoyage / Wikipedia REST** | Destination guides | 🔓 | https://en.wikipedia.org/api/rest_v1/ |
| **Alibaba Model Studio (Qwen)** ⭐ | Hero LLM | 🔑 | https://www.alibabacloud.com/help/en/model-studio/ |
| **OpenRouter** | Multi-model gateway | 🔑 (free models) | https://openrouter.ai/keys |
| **Groq** | Fast inference (free) | 🔑 | https://console.groq.com/keys |
| **Google AI Studio (Gemini)** | LLM (free tier) | 🔑 | https://aistudio.google.com/apikey |
| **Ollama** | Local models | 🔓 | https://ollama.com/ |
| **Camofox** | Browser research | 🔓 (self-host) | https://github.com/website-f/Gnosion → use Camofox project |

---

## 10. UI / UX Design System

**Principles:** mobile-first, fully responsive, zero native controls, every action has a visible state, no layout shift. Light + dark. PWA-safe (notch/safe-area).

### 10.1 Design tokens (`globals.css` / Tailwind theme)
```css
:root {
  /* Brand — "Aurora" */
  --brand-600:#4338CA; --brand-500:#4F46E5; --brand-400:#6366F1;
  --accent:#22D3EE;    /* aqua */    --warm:#FB7185;  /* coral */
  --success:#10B981; --warning:#F59E0B; --danger:#EF4444; --info:#3B82F6;
  /* Light surfaces */
  --bg:#F6F7FB; --surface:#FFFFFF; --elevated:#FFFFFF;
  --text:#0B1020; --muted:#5B6478; --border:#E6E8F0;
  /* Radii / elevation / motion */
  --r-sm:10px; --r-md:14px; --r-lg:20px; --r-pill:999px;
  --shadow-1:0 1px 2px rgba(11,16,32,.06), 0 1px 3px rgba(11,16,32,.10);
  --shadow-2:0 8px 24px rgba(11,16,32,.12);
  --ease:cubic-bezier(.2,.8,.2,1); --dur:180ms;
}
:root[data-theme="dark"]{
  --bg:#0B1020; --surface:#141B31; --elevated:#1B2440;
  --text:#E6E9F2; --muted:#94A0B8; --border:#232C47;
  --shadow-2:0 10px 30px rgba(0,0,0,.45);
}
/* Fluid type */
html{font-size:clamp(15px,0.9rem + 0.2vw,17px);}
```
- **Fonts (self-host for offline PWA):** Display = **Satoshi / General Sans** (Fontshare, free); Body = **Inter**; Mono = **JetBrains Mono** (agent event stream).
- **Breakpoints:** `sm 640 · md 768 · lg 1024 · xl 1280`. Touch targets ≥ 44px. Respect `prefers-reduced-motion`.

### 10.2 Buttons — every click shows loading + disabled (no layout shift)
```tsx
// components/ui/Button.tsx
export function Button({ loading, disabled, children, className, ...p }: BtnProps) {
  return (
    <button
      {...p}
      disabled={disabled || loading}
      aria-busy={loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-[var(--r-pill)]",
        "px-5 h-11 font-medium select-none transition-[transform,background,box-shadow]",
        "duration-[var(--dur)] ease-[var(--ease)]",
        "bg-[var(--brand-500)] text-white shadow-[var(--shadow-1)]",
        "hover:bg-[var(--brand-600)] active:scale-[.98]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
        "disabled:opacity-60 disabled:pointer-events-none",
        "min-w-[7rem]", // reserve width so spinner doesn't shift layout
        className,
      )}
    >
      {loading && <Spinner className="h-4 w-4 shrink-0" />}
      <span className={cn(loading && "opacity-90")}>{children}</span>
    </button>
  );
}
```
Variants: `primary · secondary · ghost · danger`. All share: hover, `active:scale-.98`, `focus-visible` ring, `disabled`, `loading` (spinner + `aria-busy`). Async handlers auto-toggle `loading` via a `useAsync` wrapper so devs never forget.

### 10.3 Custom Select (no native `<select>`)
Use **Radix Select** (shadcn) — fully custom, keyboard + screen-reader accessible, animated panel, custom chevron. Never `<select>`.
```tsx
<Select.Root value={v} onValueChange={setV}>
  <Select.Trigger className="h-11 rounded-[var(--r-md)] border border-[var(--border)]
    bg-[var(--surface)] px-4 flex items-center justify-between gap-2
    focus-visible:ring-2 focus-visible:ring-[var(--accent)] data-[state=open]:border-[var(--brand-400)]">
    <Select.Value placeholder="Choose…" /> <ChevronDown className="h-4 w-4 opacity-60" />
  </Select.Trigger>
  <Select.Portal>
    <Select.Content position="popper" sideOffset={6}
      className="rounded-[var(--r-md)] border border-[var(--border)] bg-[var(--elevated)]
        shadow-[var(--shadow-2)] p-1 animate-in fade-in-0 zoom-in-95">
      {/* Select.Item with check indicator, hover, keyboard nav */}
    </Select.Content>
  </Select.Portal>
</Select.Root>
```
Same rule for **checkbox, radio, switch, slider, tooltip, dropdown, tabs, dialog** → all Radix-based, custom-styled.

### 10.4 Notifications & confirms (no `alert()` / `confirm()`)
- **Toasts** via **Sonner**, themed to tokens: `notify.success() · error() · info() · promise()`.
- **Confirm** via a custom `<ConfirmDialog>` (Radix AlertDialog) returning a Promise — replaces `window.confirm`.
```ts
const ok = await confirm({ title: "Apply recovery plan?",
  body: "This rebooks your flight and updates 3 activities.",
  confirmText: "Apply", tone: "brand" });
if (ok) { /* … */ }
```

### 10.5 Custom scrollbars + scroll progress (no default indicators)
```css
/* Custom scrollbar (WebKit + Firefox) */
*{scrollbar-width:thin; scrollbar-color:var(--brand-400) transparent;}
*::-webkit-scrollbar{width:10px;height:10px;}
*::-webkit-scrollbar-thumb{
  background:linear-gradient(var(--brand-400),var(--accent));
  border-radius:var(--r-pill); border:2px solid transparent; background-clip:content-box;}
*::-webkit-scrollbar-thumb:hover{background:var(--brand-500);}
*::-webkit-scrollbar-track{background:transparent;}
/* Custom top scroll-progress bar (JS sets --p 0→1) */
.scroll-progress{position:fixed;top:0;left:0;height:3px;width:100%;transform-origin:0 50%;
  transform:scaleX(var(--p,0));background:linear-gradient(90deg,var(--brand-500),var(--accent));z-index:60;}
```

### 10.6 Big modal loading overlay (backdrop + blur + scroll-lock)
Used for heavy operations (planning a trip, running the disruption recovery). Locks scroll, blurs backdrop, traps focus, shows the agent animation.
```tsx
export function LoadingOverlay({ open, title, sub }: OverlayProps) {
  useScrollLock(open); useFocusTrap(open);
  return (
    <AnimatePresence>
      {open && (
        <motion.div initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}
          role="dialog" aria-modal="true" aria-live="assertive"
          className="fixed inset-0 z-[80] grid place-items-center
            bg-black/40 backdrop-blur-md p-6">
          <motion.div initial={{y:12,scale:.98}} animate={{y:0,scale:1}}
            className="w-full max-w-md rounded-[var(--r-lg)] bg-[var(--elevated)]
              border border-[var(--border)] shadow-[var(--shadow-2)] p-8 text-center">
            <AgentPulse className="mx-auto h-16 w-16" />
            <h3 className="mt-4 font-[Satoshi] text-lg">{title ?? "Journava is working…"}</h3>
            <p className="mt-1 text-sm text-[var(--muted)]">{sub}</p>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
```
Also provide **inline skeletons** (not spinners) for content areas, and **empty states** with an action.

### 10.7 App shell / layout (responsive)
```
Desktop (≥lg)                         Mobile (<md)
┌─────────┬────────────────┬────────┐  ┌────────────────────┐
│ Sidebar │  Top bar       │ Agent  │  │ Top bar            │
│ (nav,   ├────────────────┤ stream │  ├────────────────────┤
│  trips) │  Main content  │ panel  │  │ Main content       │
│         │  (Command /    │ (React │  │ (agent stream →    │
│         │   Research /   │  Flow) │  │  swipe-up drawer)  │
│         │   Trip)        │        │  ├────────────────────┤
└─────────┴────────────────┴────────┘  │ Bottom tab nav     │
                                        └────────────────────┘
```
- Sidebar collapses to icons at `md`, becomes **bottom tab bar** at `sm`.
- Right agent panel becomes a **swipe-up drawer** on mobile.
- CSS Grid shell, `min-w-0` on flex children (no horizontal overflow), `env(safe-area-inset-*)` padding for PWA.

### 10.8 Component checklist (maps to the request)
- [x] No native `<select>` → Radix Select
- [x] No `alert()`/`confirm()` → Sonner toasts + ConfirmDialog
- [x] No default scroll indicator → custom scrollbar + scroll-progress
- [x] Buttons: loading + disabled + no layout shift + `aria-busy`
- [x] Big modal loading with blurred backdrop + scroll-lock + focus-trap
- [x] Fully responsive shell (sidebar → bottom nav, right panel → drawer)
- [x] Skeletons, empty states, reduced-motion, light/dark

---

## 11. Repo Structure & Docker Layout

```
journava/
├─ web/                     # Vite + React PWA
│  ├─ src/
│  │  ├─ components/ui/     # Button, Select, Toast, LoadingOverlay, ConfirmDialog…
│  │  ├─ features/          # command-center, research, trip, agent-control, profile
│  │  ├─ lib/               # api client, sse, useAsync, theme
│  │  └─ styles/globals.css
│  ├─ vite.config.ts        # + vite-plugin-pwa
│  └─ Dockerfile
├─ api/                     # FastAPI + LangGraph
│  ├─ app/
│  │  ├─ agents/            # chief, flight, hotel, research, weather_risk, budget, itinerary, memory
│  │  ├─ tools/             # atlas_skill, amadeus, open_meteo, youtube, reddit, gdelt, halal, camofox …
│  │  ├─ brain/             # gnosion_client.py (library) + mcp bootstrap
│  │  ├─ graph/             # langgraph supervisor + edges
│  │  ├─ core/              # sse, llm (litellm), cache, db, settings
│  │  └─ main.py
│  ├─ pyproject.toml        # uv
│  └─ Dockerfile
├─ skills/
│  └─ atlas-flight-booking/ # vendored Atlas skill (npx skills add …) → atlas-flight CLI
├─ gnosion/                 # brain data + MCP service (gns mcp)
├─ camofox/                 # browser research service
├─ ops/
│  ├─ docker-compose.yml
│  ├─ deploy.sh             # follows the shared-reverse-proxy recipe
│  └─ .env.example
└─ JOURNAVA_PLAN.md
```

**Compose services:** `web · api · gnosion · camofox · postgres · redis`. Internal only; the shared Caddy fronts `web` (and `/api` → `api`). Suggested internal port block **8400–8409** — *verify against the reverse-proxy port table before use* (Sejuk Ops already reserves 8300–8309).

---

## 12. Implementation Roadmap

Weave **Qoder** through every phase (evidence for the 20%).

**Phase 0 — Scaffold (Qoder)**
Repo, docker-compose, Caddy registration, DB schema, LiteLLM + Qwen wired, health checks, UI design-system components (§10) first.

**Phase 1 — Core loop (MVP demo-able)**
Chief + Flight (Atlas skill, sandbox) + Hotel + Itinerary agents · Command Center + Research Board + **Profile page & preference scoping** · SSE agent stream · Gnosion library memory · Redis cache.

**Phase 2 — Intelligence**
Research Agent (Camofox + YouTube/Reddit) · Weather/Risk (Open-Meteo + GDELT) · Budget (Frankfurter) · Verification + Reflexion loop · Gnosion MCP + d3 graph in Agent Control Center.

**Phase 3 — The wow + polish**
Disruption simulation → autonomous recovery · explainability ("why this?") · PWA install · demo data + caching · record Qoder Outcomes evidence.

---

## 13. Deployment

- **Behind the shared `/opt/reverse-proxy` (Caddy)** — never spin up a second TLS terminator. Add a Caddyfile block routing `journava.<domain>` → `web`, `journava.<domain>/api/*` → `api`.
- **Flow:** Qoder → GitHub → VPS → `docker compose up -d` (via `ops/deploy.sh`, which follows the shared-proxy add-project recipe).
- **Env:** all keys in `.env` (see §9). `.env.example` committed; real `.env` never committed.
- **Data:** Postgres volume + `data/journava.gnosion` (brain) persisted + backed up.
- **CI (optional):** GitHub Actions → build images → SSH deploy → compose pull/up.

---

## 14. Demo & Submission Plan

**Submission description (2–3 sentences):**
> Journava is an autonomous multi-agent travel platform where a Chief Agent orchestrates specialized AI agents — flights, hotels, research, budget, weather/risk — that plan, verify, and continuously adapt an entire trip in real time. It fuses the official **Atlas Flight Booking Skill** (real search→book→ticket) with human-like browser research, a self-improving memory brain (Gnosion), and a personal preference profile (e.g. halal-certified dining), so when a disruption hits, the agents autonomously rebuild the itinerary instead of just answering a prompt. Built primarily with Alibaba Cloud's Qoder, it's an extensible "operating system for travel" spanning every hackathon track.

**Video (3–5 min): 70% real demo / 20% presentation / 10% cinematic.**
Hook → problem → agents activate → itinerary → **flight-disruption money shot** → "why this?" explainability + Gnosion brain graph → 15s architecture → close ("Your journey. Our agents."). Tools: OBS → CapCut; phone mockups via CapCut/Canva/Placeit. Optional separate 30–60s cinematic commercial.

---

## 15. Honest Risks & Caveats

- **Flights are the hard gap** — no great free-unlimited fare API. Atlas + Amadeus test + Camofox verification is the mitigation; keep the demo dataset cached.
- **Google Places / YouTube are not "free"** — billable with free monthly caps. Set quotas + budget alerts + cache; call it a "free monthly allowance" in the writeup.
- **Scraping ToS** — official API first, permitted public pages second, never bypass logins/paywalls/captcha. Present Camofox as *research*, not *bypass*.
- **Atlas skill auth is headless-unfriendly** — it uses browser OAuth + OS keychain. Authenticate once on the dev/demo machine in **sandbox**; a bare headless VPS needs the credential pre-provisioned before the demo.
- **Halal data is inconsistent** — always label confidence (**certified / Muslim-friendly / unverified**); never claim "certified" without a certification source.
- **Scope discipline** — pitch 20 agents, **ship 8 real ones**. Feasibility (30%) rewards depth over breadth.
- **Name clearance** — "Journava" has no existing travel app/brand found, but do a `.com`/`.app` domain + trademark check before public launch.

---

*End of spec. Next step: scaffold Phase 0 (repo + compose + design-system components) in Qoder.*
