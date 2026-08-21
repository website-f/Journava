# Journava — Judge Demo Script

**One line:** *Journava is agentic travel infrastructure — the same 21-agent mesh plans a traveller's trip, runs an agency's client book, and operates a hotel's property, moving real money end-to-end through Atlas.*

Runs against the local stack at `http://127.0.0.1:8401` (or your VPS domain).

**Seeded logins** (password `Journava!2026`):
- `traveler@journava.test` — consumer PWA
- `hotel@journava.test` — partner **console** (agency + hotel modes)
- `admin@journava.test` — platform admin (stays on the PWA)

**Pre-flight (once):** connect a Telegram bot under **Account → Integrate** and note a real chat id from `@userinfobot`; set `PUBLIC_BASE_URL` so share links use your domain. Everything else works out of the box (Atlas sandbox keys are in the vault).

---

## The 6-minute run

### 0. The hook (20s)
> "Travel apps help one traveller. Journava is the agent layer underneath the whole industry — travellers, agencies, and hotels all run on the same mesh, and it settles real money. Let me show all three."

### 1. Consumer — plan + the breakthrough tiers (90s)
Log in as **traveler**. On the home screen:
1. **Plan a trip** — "5-day Bali trip in December, halal, budget 6000 MYR." Watch the agents stream live. Result page: flights (Atlas sandbox — *bookable, real*), hotels, day-by-day itinerary, budget, safety.
2. **Plan from a social post** *(interesting touch)* — open the floating **AI assistant** → paste a caption: *"3 days in Chengdu 🐼 panda base, hotpot at Shu Jiu Xiang, Jinli Street, Leshan Buddha."* → it extracts the destination + places and launches a full plan in the background, tracked live in the chat.
3. Open **My Trip → Flight watch** → choose **Demo: delay** → the agent detects it and **auto-reschedules within budget** *(common practice, done well)*.
4. **My Trip → Itinerary dependency graph** → **Simulate a 200-min delay** → the graph cascades: the **return flight flags "missed connection"**, a late meal flags "likely closed", the trip is re-planned and **the fare difference settles in real time** *(major breakthrough)*.

### 2. The ×2 — AI adjudicated refund (40s)
Still consumer-side value, shown in the console. Log in as **hotel@journava.test** → **Escrow & refunds**:
- Open a hold from the active trip → pick **Flight cancelled** → **Adjudicate**.
- An agent returns a **verdict** ("full refund, 100%") with an **EU261 rationale and policy basis**, splits refund vs release, and settles it — **no human in the loop**. *"This is the multiplier: an agent adjudicating money on its own."*

### 3. Agency — plan FOR a client, deliver a PDF + link (60s)
Console **My clients** mode → **Clients**:
1. Add a client (name + a real Telegram chat id, or a WhatsApp number + channel).
2. Type a destination → **Build full package** → the mesh runs a full trip.
3. **Compile & send** → a **branded PDF** is generated and **sent to the client on Telegram** (with the interactive link as caption); open the **`/s/<token>` link** — the client sees the *same interactive plan*, no account. *"The agency's agents did the whole thing; the client gets a real deliverable."*

### 4. Hotel — the supply→demand→money loop (90s)
Console **My property** mode:
1. **Listings** → **AI listing composer**: type a city + room hint → **Draft with AI** writes the description, perks, and a suggested price → **Publish**. The banner shows it's **live to travellers** and ranked ahead of the OTAs.
2. **Inventory firewall** → **Run drill: two channels, one room** → exactly one confirms, one is **blocked — a double-booking prevented atomically** *(notable advance)*.
3. **Bookings → New booking** → pick the room, a guest, dates → **Book & notify**: it passes the firewall, and the **manager gets a Telegram ping**.
4. **Finance** → the booking is there as **income**; hit **Summarise** for an **AI readout** of the ledger; click **PDF** on the row → a **formatted receipt**. The earlier adjudicated refund shows as a **refund** row. *"Every ringgit — bookings in, refunds out — on one page, each with a receipt."*

### 5. Close (20s)
> "Same agents. Real Atlas money in and settled. A firewall that stops oversells before they happen, an itinerary that heals itself, and an agent that adjudicates refunds. Consumers, agencies, and hotels — one platform, bypassing the OTAs."

---

## Judging-criteria map
- **Innovation** — itinerary-as-dependency-graph self-heal; AI escrow adjudicator; inventory firewall; social-post → trip.
- **Feasibility** — real Atlas sandbox (search/verify/order/pay), Dockerized stack, Postgres-backed, honest labelled fallbacks where a live source is walled.
- **Qoder / dev-tool** — MCP server (`journava-mcp/`) exposes the mesh as tools callable from Claude Desktop.
- **Demo** — the four disruption/firewall/refund "money shots" above.

## Honest notes (say these if asked)
- Flight booking + fare settlement are **real** against the Atlas *sandbox* (no real money). Atlas has no refund endpoint, so refunds attempt a real call then settle on an **Atlas-backed ledger** — clearly labelled.
- Social **URL** crawl / oEmbed and **WhatsApp** need outbound network + creds; on stage, drive social with a **pasted caption or screenshot**, and use the **Telegram** channel (WhatsApp shows a labelled "not configured" until `WHATSAPP_TOKEN`/`PHONE_ID` are set).
- Use the **Demo:** toggles for delay/cancellation so the disruption/graph/escrow flows are deterministic live.
