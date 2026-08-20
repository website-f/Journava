# Journava — Hackathon Demo Kit

Everything you need to submit and present: the one-liner + description, a 4-minute
video script, a live-demo runbook with exact clicks, the judging-criteria map, and
the Qoder evidence checklist.

> Stack is live locally at **http://localhost:8401** (6 containers). Seeded logins,
> password **`Journava!2026`**: `traveler@journava.test` · `hotel@journava.test`
> (partner) · `admin@journava.test` (platform admin).

---

## 1. Positioning

**Name:** Journava — *Travel, run by agents.*

**One-liner:** An autonomous multi-agent travel platform where a Chief Agent
orchestrates specialist agents that plan, research, verify and adapt an entire
trip in the background — and a B2B side that lets hotels sell direct, not via OTAs.

**Submission description (2–3 sentences):**
> Journava is a secured, multi-tenant agentic travel platform: a Chief Agent
> dispatches specialist agents (flights, hotels, research, weather/risk, budget,
> itinerary…) that run in the background, fuse official APIs with human-like
> browser research, verify prices, and remember every trip in a self-improving
> memory brain (Gnosion). It goes beyond a chatbot — when a flight is disrupted
> the agents rebuild the itinerary autonomously — and beyond travel: the same
> runtime "hires" non-travel agents (e.g. an email-replier). A built-in Supplier
> Portal lets hotels list inventory that surfaces as bookable **direct** options
> (no OTA commission, they keep the guest). Built primarily with Alibaba Cloud's
> Qoder.

**Category / tracks:** the "ninth answer" — one agentic OS spanning Flights,
Hotels, Attractions, Activities, Payments, Data & Analytics, **AI Agent Ecosystem**
(orchestration + a no-code-ish supplier onboarding), and Other (sustainable/gen).

---

## 2. The 4-minute submission video (70% real demo)

Record with OBS; edit in CapCut. Keep it mostly the real product.

| Time | Beat | On screen |
|---|---|---|
| 0:00–0:15 | **Hook** | Black → "Travel means juggling 20 apps." Quick cuts: flights, hotels, reviews, weather, visa, payments → "What if a team of agents did it for you?" → **JOURNAVA** logo. |
| 0:15–0:35 | **Sign in + home** | Log in (native-app UI, glass bottom nav). Personalized home greets you with **"For you"** cards from your real history. |
| 0:35–1:25 | **Magic moment (background agents)** | Home → type *"cheap flights from KLIA to BKI on 6 Nov, night"* → **agents start in the background**, the "agents working" modal streams the live log. Tap **"Watch in workspace"** → Agents page: **Topology** graph lighting up, **Live** event stream. Results: real **Google Flights** fares (MYR 432…), filtered to **night**, cheapest picked. |
| 1:25–2:05 | **Explainability + memory** | Open a result → "Why this?" reasoning + source badges (Direct / Research / Simulated — honest labels). Mention Gnosion **Brain** tab (knowledge graph) — "it remembers and gets smarter each trip." |
| 2:05–2:45 | **THE WOW — disruption recovery** | Trip → Itinerary → **Simulate disruption**. Don't touch anything: Flight → Risk → Hotel → Transport → Budget agents cascade in the modal → **"Recovery plan ready — additional cost RM0"** → Accept. *This is agentic, not chatbot.* |
| 2:45–3:20 | **Two-sided marketplace (the bonus)** | Switch to `hotel@` → **Partner Portal**: add a room at Kinabalu Bay Resort. Switch to traveler → hotel search for Kota Kinabalu → that room appears as **"Direct · no OTA fee" bookable** above the OTA options → **Book direct** → back to `hotel@` → the **lead** is there. |
| 3:20–3:40 | **Beyond travel + Qoder** | One line: "Same runtime, new agent" — show the agent **catalog** (email-replier in `productivity`). "Built with Qoder" slide + 5s of Qoder editing the repo. |
| 3:40–4:00 | **Close** | "You didn't search 20 sites. Your agents did." → **JOURNAVA — Travel, run by agents.** |

Optional separate 30–60s cinematic commercial (phone mockups, CapCut templates).

---

## 3. Live-demo runbook (exact clicks)

**Pre-flight (once):**
- `docker compose --profile full up -d` → confirm `curl localhost:8400/health` shows `postgres:true`.
- As **admin@** → Account → **Engine** → add an LLM key (Groq) so agents have a model.
- Pre-warm the flight search once (Camofox first crawl is slower) so the live run is snappy.

**The run (as traveler@):**
1. **Home** → prompt: *"cheap flights from KLIA to BKI on 6 Nov night"* → Run.
2. "Agents working" modal → **Watch in workspace** → show Topology + Live.
3. Back to results → open a flight → **Why this?** + source badges.
4. **Trip → Itinerary → Simulate disruption** → watch cascade → **Accept recovery**.
5. Hotels: Home → *"hotels in Kota Kinabalu"* → point out the **Direct · no OTA fee** card → **Book direct**.

**Marketplace (as hotel@):**
6. Account → **Partner** → add property "Kinabalu Bay Resort" (Kota Kinabalu, halal) + a listing → show it's now bookable in traveler search → after the traveler's "Book direct", show the **lead** in the Leads tab.

**Beyond travel (optional):** `GET /api/v1/agents/catalog` → 22 agents / 2 domains; run the email-replier as a background task job.

---

## 4. Judging criteria → where it lands

| Criterion | Weight | Evidence in the demo |
|---|---|---|
| **Innovation** | 30% | Background multi-agent orchestration + self-improving memory (Gnosion) + autonomous **disruption recovery** + a two-sided **direct-booking** marketplace. |
| **Feasibility** | 30% | It actually runs: secured login, real Google Flights fares via Camofox, verified/labeled sources, Docker stack, per-user data. 8 real agents, extensible to more. |
| **Qoder** | 20% | Built primarily in Qoder (keep `.qoder/rules`, commits, a screen-recording of Qoder editing + tests passing). |
| **Demo** | 20% | Native-app glass UI, live agent workspace, the disruption money-shot, both sides of the marketplace. |

---

## 5. Qoder evidence checklist (for the 20%)
- [ ] `.qoder/rules` present in the repo (project rules).
- [ ] A short screen recording: Qoder prompt → edits files → tests/build pass → app runs.
- [ ] A "Built with Qoder" slide in the deck.
- [ ] Commit history / task list showing Qoder-driven work across days.

---

## 6. Honest caveats to keep the story tight
- **Prices are read live but not held fares** — Camofox surfaces real Google Flights
  results; truly *bookable* fares are Atlas's job (needs the headless keyring +
  sandbox key). Supplier **direct** listings are genuinely bookable-as-lead today.
- **Don't claim 20 fully-autonomous agents** — demo the ~8 real ones well; the rest
  are the extensible roadmap.
- Frame Camofox as **research**, not scraping-around-blocks (official API → permitted
  public research → never bypass access controls).
