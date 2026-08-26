-- Journava schema (idempotent — safe to re-run on every boot).
-- Structured record only; semantic memory lives in Gnosion.

CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT UNIQUE NOT NULL,
    display_name TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The Traveler Profile (spec §3.5 / §7.5). Preferences narrow agent scope;
-- an absent preference means the agent searches globally.
CREATE TABLE IF NOT EXISTS traveler_profiles (
    user_id         UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    halal_required  BOOLEAN NOT NULL DEFAULT FALSE,
    allergies       TEXT[] NOT NULL DEFAULT '{}',
    cuisine_likes   TEXT[] NOT NULL DEFAULT '{}',
    interests       TEXT[] NOT NULL DEFAULT '{}',
    pace            TEXT NOT NULL DEFAULT 'balanced',
    budget_currency TEXT NOT NULL DEFAULT 'MYR',
    home_airport    TEXT,
    max_connections INTEGER,
    avoid_red_eye   BOOLEAN NOT NULL DEFAULT FALSE,
    accessibility   JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Anything not modelled above (loyalty programs, companions, language…).
    extras          JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trips (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID REFERENCES users(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    goal          TEXT,                        -- the original natural-language request
    destination   TEXT,
    origin        TEXT,
    start_date    DATE,
    end_date      DATE,
    travellers    INTEGER NOT NULL DEFAULT 1,
    budget_amount NUMERIC(12, 2),
    budget_currency TEXT NOT NULL DEFAULT 'MYR',
    status        TEXT NOT NULL DEFAULT 'planning',  -- planning|active|completed|cancelled
    -- The full agent-result envelope for this plan. Storing the snapshot (rather
    -- than only the normalised columns) is what lets the My Trip page rebuild a
    -- trip verbatim after a restart, without replaying 21 agents.
    plan_snapshot JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotent add for databases created before plan_snapshot existed.
ALTER TABLE trips ADD COLUMN IF NOT EXISTS plan_snapshot JSONB;

CREATE INDEX IF NOT EXISTS trips_created_idx ON trips (created_at DESC);

CREATE TABLE IF NOT EXISTS itinerary_items (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id     UUID NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    day_index   INTEGER NOT NULL,
    starts_at   TIMESTAMPTZ,
    ends_at     TIMESTAMPTZ,
    kind        TEXT NOT NULL,           -- flight|hotel|activity|meal|transport
    title       TEXT NOT NULL,
    details     JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- "Why did Journava choose this?" — explainability is a product requirement.
    reasoning   TEXT,
    cost_amount NUMERIC(12, 2),
    cost_currency TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS itinerary_items_trip_day_idx
    ON itinerary_items (trip_id, day_index);

CREATE TABLE IF NOT EXISTS bookings (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id       UUID NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,          -- flight|hotel|activity
    provider      TEXT NOT NULL,          -- atlas|amadeus|hotelbeds…
    provider_ref  TEXT,                   -- order id / PNR
    status        TEXT NOT NULL DEFAULT 'pending',
    -- Booking-time requests such as the halal special meal (MOML).
    special_requests JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    total_amount  NUMERIC(12, 2),
    currency      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only agent activity log; also replayed into the SSE stream.
CREATE TABLE IF NOT EXISTS agent_events (
    id         BIGSERIAL PRIMARY KEY,
    trip_id    UUID REFERENCES trips(id) ON DELETE CASCADE,
    agent      TEXT NOT NULL,
    status     TEXT NOT NULL,            -- idle|active|working|monitoring|waiting
    message    TEXT NOT NULL,
    data       JSONB NOT NULL DEFAULT '{}'::jsonb,
    caused_by  TEXT,                     -- the agent that handed off
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_events_trip_created_idx
    ON agent_events (trip_id, created_at DESC);

-- Outcome learning (spec §7 ③) — accepted/rejected choices feed back to Gnosion.
CREATE TABLE IF NOT EXISTS decision_outcomes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id     UUID REFERENCES trips(id) ON DELETE CASCADE,
    agent       TEXT NOT NULL,
    domain      TEXT NOT NULL,           -- flight|hotel|activity|restaurant
    recommendation JSONB NOT NULL,
    accepted    BOOLEAN NOT NULL,
    user_note   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- API Vault — every third-party credential (spec §9), encrypted at rest.
-- Keys live here, never in .env. Only a masked hint is ever returned by the API.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_credentials (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- One row per provider: re-adding a key rotates it rather than creating a
    -- duplicate that would rotate unpredictably.
    provider         TEXT NOT NULL UNIQUE,
    label            TEXT NOT NULL,
    category         TEXT NOT NULL DEFAULT 'other',
    secret_encrypted TEXT,                       -- Fernet ciphertext, nullable
    masked_secret    TEXT NOT NULL DEFAULT '',   -- e.g. "sk-…4f2a"
    -- Non-secret companions: client ids, account ids, base URLs, environment.
    extra            JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    -- untested | healthy | rate_limited | limit_reached | invalid | disabled
    status           TEXT NOT NULL DEFAULT 'untested',
    status_detail    TEXT,
    last_tested_at   TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS api_credentials_category_idx
    ON api_credentials (category, provider);

-- ---------------------------------------------------------------------------
-- Notification bots (Telegram). Multiple bots, each toggleable — a background
-- plan pings every enabled one. Token is Fernet-encrypted; only a hint is
-- returned by the API.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification_bots (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label            TEXT NOT NULL,
    platform         TEXT NOT NULL DEFAULT 'telegram',
    token_encrypted  TEXT NOT NULL,
    token_hint       TEXT NOT NULL DEFAULT '',
    chat_id          TEXT NOT NULL,
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Knowledge base — durable findings the agents document from every plan, so the
-- Research page reads like a growing library ("Tokyo hotels run RM…", "Australia
-- refuses passports renewed >10y ago") and future plans get smarter by reading it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_notes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Natural key so re-observing a fact updates it instead of duplicating.
    dedup_key    TEXT NOT NULL UNIQUE,
    category     TEXT NOT NULL,        -- flights|hotels|visa|food|activities|weather|safety|budget|transport|general
    destination  TEXT,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    tags         TEXT[] NOT NULL DEFAULT '{}',
    confidence   TEXT NOT NULL DEFAULT 'observed',
    source       TEXT,
    seen_count   INT NOT NULL DEFAULT 1,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS knowledge_category_idx
    ON knowledge_notes (category, destination);

-- ---------------------------------------------------------------------------
-- Flight bookings (Atlas). Mirrors the CLI's opaque identifiers so a booking
-- can be resumed: search → verify → confirm price → order → pay → ticket.
-- Passenger details are deliberately NOT stored: the CLI treats them as
-- one-time input excluded from persisted state, and so do we.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flight_bookings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id         UUID REFERENCES trips(id) ON DELETE SET NULL,
    -- Opaque Atlas identifiers, stored verbatim.
    offer_id        TEXT,
    booking_id      TEXT,
    order_no        TEXT,
    confirmation_id TEXT,
    environment     TEXT NOT NULL DEFAULT 'sandbox',   -- sandbox | production
    -- draft | price_confirmed | ordered | paying | paid | ticketed | failed
    stage           TEXT NOT NULL DEFAULT 'draft',
    last_code       TEXT,                              -- last Atlas response code
    last_message    TEXT,
    route           TEXT,
    depart_date     DATE,
    travellers      INTEGER NOT NULL DEFAULT 1,
    total_amount    NUMERIC(12, 2),
    currency        TEXT,
    -- Whole normalised offer plus the response envelopes, for the history page.
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    simulated       BOOLEAN NOT NULL DEFAULT TRUE,     -- sandbox rehearsal?
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS flight_bookings_created_idx
    ON flight_bookings (created_at DESC);
CREATE INDEX IF NOT EXISTS flight_bookings_order_idx
    ON flight_bookings (order_no);

-- Search history — every scoped run, so the History page can show what was
-- asked and reopen the result without replaying the agents.
CREATE TABLE IF NOT EXISTS search_history (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trip_id       UUID REFERENCES trips(id) ON DELETE SET NULL,
    scope         TEXT NOT NULL,
    goal          TEXT NOT NULL,
    destination   TEXT,
    origin        TEXT,
    agent_count   INTEGER NOT NULL DEFAULT 0,
    duration_ms   INTEGER,
    option_count  INTEGER NOT NULL DEFAULT 0,
    result_snapshot JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS search_history_created_idx
    ON search_history (created_at DESC);

-- LLM provider configuration (Phase 3: Engine management page).
-- The failover chain is determined by priority (lower = tried first).
CREATE TABLE IF NOT EXISTS llm_providers (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- NOT unique on purpose: the pool holds MANY entries per provider so an
    -- operator can pool several keys for the same provider/model (round-robin
    -- across free-tier quotas). Rows are distinguished by id + masked_key.
    name          TEXT NOT NULL,               -- "Groq", "OpenRouter", "DashScope", etc.
    litellm_model TEXT NOT NULL,               -- "groq/llama-3.3-70b-versatile"
    api_key       TEXT NOT NULL,               -- Fernet ciphertext (see core/vault.py)
    priority      INTEGER NOT NULL DEFAULT 0,  -- lower = tried first
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    max_rpm       INTEGER,                     -- optional rate-limit guard
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Health + quota columns, added idempotently so an existing deployment upgrades.
-- Providers don't expose a standard "remaining quota", so ceilings are operator
-- set and usage is metered locally (Redis) against them.
ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS
    status TEXT NOT NULL DEFAULT 'untested';   -- untested|healthy|rate_limited|
                                               -- limit_reached|invalid|disabled
ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS status_detail TEXT;
ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS last_tested_at TIMESTAMPTZ;
ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ;
-- Cooldown after a 429, so a rate-limited key is skipped instead of hammered.
ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS cooldown_until TIMESTAMPTZ;
ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS max_rpd INTEGER;
ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS max_tpd INTEGER;
-- Masked hint so the UI can identify a key without ever decrypting it.
ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS masked_key TEXT NOT NULL DEFAULT '';
-- True once the key has been encrypted by the vault; false for legacy plaintext
-- rows written before encryption existed, which are migrated on first read.
ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS key_encrypted BOOLEAN NOT NULL DEFAULT FALSE;
-- Drop the legacy UNIQUE(name): a second "Groq" (a different key, or the same
-- model with a different key) used to violate it and surface as a spurious
-- "database unavailable". The pool is meant to hold many entries per provider.
ALTER TABLE llm_providers DROP CONSTRAINT IF EXISTS llm_providers_name_key;

CREATE INDEX IF NOT EXISTS llm_providers_priority_idx
    ON llm_providers (enabled, priority, created_at);

-- Append-only LLM usage log for the Engine stats dashboard.
CREATE TABLE IF NOT EXISTS llm_usage (
    id          BIGSERIAL PRIMARY KEY,
    provider_id UUID REFERENCES llm_providers(id) ON DELETE SET NULL,
    model       TEXT NOT NULL,
    agent       TEXT,                          -- which agent called it
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    latency_ms  INTEGER,
    success     BOOLEAN NOT NULL,
    error_msg   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS llm_usage_provider_created_idx
    ON llm_usage (provider_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Auth & multi-tenant identity (Phase 1). Extends the existing `users` table
-- with credentials + a platform-admin flag, and adds organizations, org
-- memberships (roles), and refresh-token sessions for rotation/revocation.
-- ---------------------------------------------------------------------------
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS organizations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'personal',  -- personal | agency | platform
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memberships (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'member',     -- owner | admin | staff | member
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, org_id)
);
CREATE INDEX IF NOT EXISTS memberships_user_idx ON memberships (user_id);
CREATE INDEX IF NOT EXISTS memberships_org_idx ON memberships (org_id);

-- Refresh-token sessions. Only the SHA-256 of the token is stored, so a DB leak
-- never yields a usable token; rotation revokes the old row and inserts a new one.
CREATE TABLE IF NOT EXISTS auth_sessions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_hash  TEXT NOT NULL,
    expires_at    TIMESTAMPTZ NOT NULL,
    revoked_at    TIMESTAMPTZ,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_sessions_hash_idx ON auth_sessions (refresh_hash);
CREATE INDEX IF NOT EXISTS auth_sessions_user_idx ON auth_sessions (user_id);

-- ---------------------------------------------------------------------------
-- B2B Supplier Portal (Phase 4). A travel agency/hotel/attraction org lists
-- properties + bookable listings; those surface as a "direct" source in the
-- Hotel Agent (owns the guest, no OTA commission). Travelers create leads the
-- supplier then works. Everything is org-scoped via the memberships table.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS supplier_properties (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'hotel',   -- hotel | attraction
    city           TEXT NOT NULL,
    country        TEXT,
    description    TEXT,
    halal_friendly BOOLEAN NOT NULL DEFAULT FALSE,
    image_url      TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS supplier_properties_city_idx ON supplier_properties (lower(city));
CREATE INDEX IF NOT EXISTS supplier_properties_org_idx ON supplier_properties (org_id);

CREATE TABLE IF NOT EXISTS supplier_listings (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    property_id    UUID NOT NULL REFERENCES supplier_properties(id) ON DELETE CASCADE,
    org_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title          TEXT NOT NULL,                   -- room type / ticket name
    price_amount   NUMERIC(12,2),
    price_currency TEXT NOT NULL DEFAULT 'MYR',
    capacity       INTEGER,
    perks          TEXT[] NOT NULL DEFAULT '{}',
    available      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS supplier_listings_property_idx ON supplier_listings (property_id);

CREATE TABLE IF NOT EXISTS supplier_leads (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    property_id      UUID REFERENCES supplier_properties(id) ON DELETE SET NULL,
    listing_id       UUID REFERENCES supplier_listings(id) ON DELETE SET NULL,
    traveler_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    traveler_email   TEXT,
    note             TEXT,
    status           TEXT NOT NULL DEFAULT 'new',   -- new | contacted | booked | closed
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS supplier_leads_org_idx ON supplier_leads (org_id, created_at DESC);

-- Booking.com-style richness on listings + properties (idempotent upgrade).
ALTER TABLE supplier_listings ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE supplier_listings ADD COLUMN IF NOT EXISTS image_url TEXT;
-- Gallery: several images per room (drag-drop upload). image_url stays as the
-- cover/first image for back-compat; image_urls holds the full ordered set.
ALTER TABLE supplier_listings ADD COLUMN IF NOT EXISTS image_urls TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE supplier_listings ADD COLUMN IF NOT EXISTS original_price NUMERIC(12,2);
ALTER TABLE supplier_listings ADD COLUMN IF NOT EXISTS discount_pct INTEGER;
ALTER TABLE supplier_listings ADD COLUMN IF NOT EXISTS amenities TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE supplier_properties ADD COLUMN IF NOT EXISTS amenities TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE supplier_properties ADD COLUMN IF NOT EXISTS star_rating INTEGER;

-- Revenue Autopilot: a yield agent that watches competitor rates + demand and
-- auto-adjusts nightly prices within guardrails. One settings row per org, plus
-- an audit log of every adjustment (proposed or applied).
CREATE TABLE IF NOT EXISTS revenue_autopilot (
    org_id         UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    enabled        BOOLEAN NOT NULL DEFAULT FALSE,
    auto_apply     BOOLEAN NOT NULL DEFAULT FALSE,
    max_change_pct INTEGER NOT NULL DEFAULT 15,   -- cap on a single run's move
    floor_pct      INTEGER NOT NULL DEFAULT 60,   -- never price below this % of the list price
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS price_adjustments (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    listing_id   UUID REFERENCES supplier_listings(id) ON DELETE CASCADE,
    room_title   TEXT,
    old_price    NUMERIC(12,2),
    new_price    NUMERIC(12,2),
    delta_pct    NUMERIC(6,2),
    demand_level TEXT,
    rationale    TEXT,
    applied      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS price_adjustments_org_idx ON price_adjustments (org_id, created_at DESC);

-- Autonomous Boardroom: the org's agents convene on their own to discuss revenue,
-- bookings and marketing, and record decisions + action items. One settings row
-- per org, plus a log of every meeting's minutes.
CREATE TABLE IF NOT EXISTS boardroom_settings (
    org_id      UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    enabled     BOOLEAN NOT NULL DEFAULT FALSE,   -- include in the scheduled convene
    focus       TEXT,                             -- a standing objective for the room
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS boardroom_meetings (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    topic            TEXT,
    summary          TEXT,
    transcript       JSONB NOT NULL DEFAULT '[]',   -- [{speaker, emoji, role, text}]
    decisions        JSONB NOT NULL DEFAULT '[]',   -- [str]
    action_items     JSONB NOT NULL DEFAULT '[]',   -- [{owner, action}]
    marketing_draft  TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS boardroom_meetings_org_idx ON boardroom_meetings (org_id, created_at DESC);

-- Discovery: a traveller snaps a photo, the AI camera identifies it (vision +
-- Camofox references), and they can save it as a "travel note" on their
-- Discovery page.
CREATE TABLE IF NOT EXISTS discoveries (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    image_url   TEXT,                          -- compact data URL of the snapped photo
    title       TEXT,
    category    TEXT,
    description TEXT,
    facts       JSONB NOT NULL DEFAULT '[]',
    links       JSONB NOT NULL DEFAULT '[]',   -- [{type, title, url}]
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS discoveries_user_idx ON discoveries (user_id, created_at DESC);

-- A published, brandable public page per business (the "direct hotel site"):
-- logo + about, reachable at /h/{slug} with no account. Mirrors package_pages.
CREATE TABLE IF NOT EXISTS org_profiles (
    org_id     TEXT PRIMARY KEY,
    slug       TEXT UNIQUE NOT NULL,
    name       TEXT,
    logo_url   TEXT,
    about      TEXT,
    published  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Corporate travel policy (Phase 2.3). One active policy per org — fare caps,
-- cabin rules, preferred carriers/hotels, approval thresholds. The Flight/Hotel
-- agents read it as an org-policy layer on top of the traveller's own prefs and
-- flag violations; the Agency console shows compliance + duty-of-care + ESG.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS org_policies (
    org_id      UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    policy      JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Escrow ledger + AI adjudication (the "impossible without AI" multiplier).
-- On booking, the fare is HELD in escrow. When something goes wrong (delay,
-- downgrade, no-show), an adjudicator agent reasons about the claim and settles
-- autonomously: release to the supplier, partial refund, or full refund. Money
-- OUT (upcharges / fare-difference top-ups) settles for real via Atlas pay.do;
-- refunds are recorded here (Atlas has no refund endpoint) after a best-effort
-- real attempt.  UUIDs are stored as TEXT because booking refs are external.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS escrow_holds (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    booking_ref  TEXT NOT NULL,
    user_id      UUID REFERENCES users(id) ON DELETE SET NULL,
    org_id       UUID REFERENCES organizations(id) ON DELETE SET NULL,
    description  TEXT,
    amount       NUMERIC(12,2) NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'MYR',
    released      NUMERIC(12,2) NOT NULL DEFAULT 0,
    refunded      NUMERIC(12,2) NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'held',  -- held | released | refunded | partial
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS escrow_holds_ref_idx ON escrow_holds (booking_ref);
CREATE INDEX IF NOT EXISTS escrow_holds_created_idx ON escrow_holds (created_at DESC);

CREATE TABLE IF NOT EXISTS escrow_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hold_id     UUID NOT NULL REFERENCES escrow_holds(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                  -- hold | release | refund | upcharge | adjust
    amount      NUMERIC(12,2) NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'MYR',
    actor       TEXT NOT NULL DEFAULT 'system', -- system | agent | user
    reason      TEXT,
    settlement  TEXT,                            -- atlas-live | ledger | simulated
    atlas_ref   TEXT,
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS escrow_events_hold_idx ON escrow_events (hold_id, created_at);

-- ---------------------------------------------------------------------------
-- Hotel inventory firewall (notable-advance tier). A supplier sells the same
-- physical rooms on several channels (our marketplace + OTAs). We hold the
-- source of truth (supplier_listings.capacity) and track each channel's
-- allocation + sales here, so the firewall can reconcile drift and — critically
-- — atomically guard a booking so two channels can't sell the last room.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS channel_inventory (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id  UUID NOT NULL REFERENCES supplier_listings(id) ON DELETE CASCADE,
    org_id      UUID REFERENCES organizations(id) ON DELETE CASCADE,
    channel     TEXT NOT NULL,                 -- journava | booking.com | agoda | expedia ...
    allocated   INTEGER NOT NULL DEFAULT 0,
    sold        INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (listing_id, channel)
);
CREATE INDEX IF NOT EXISTS channel_inventory_listing_idx ON channel_inventory (listing_id);

-- ---------------------------------------------------------------------------
-- Partner delivery: agency clients + shareable compiled plans.
-- An agency plans a trip FOR a client, compiles it to a PDF, and sends it over
-- Telegram (WhatsApp later) with an interactive share link as the fallback.
-- shared_plans is read WITHOUT auth via a token, so a client with no account can
-- open the interactive view.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agency_clients (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    email            TEXT,
    telegram_chat_id TEXT,
    whatsapp         TEXT,
    channel          TEXT NOT NULL DEFAULT 'telegram',  -- telegram | whatsapp | both
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agency_clients_org_idx ON agency_clients (org_id, created_at DESC);

-- Where a client/lead came from, and the auto-planned package attached to it, so
-- a lead captured from the public Package Builder carries its AI-drafted plan.
ALTER TABLE agency_clients ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual';  -- manual | package_page
ALTER TABLE agency_clients ADD COLUMN IF NOT EXISTS destination TEXT;
ALTER TABLE agency_clients ADD COLUMN IF NOT EXISTS job_id TEXT;        -- the auto-plan job
ALTER TABLE agency_clients ADD COLUMN IF NOT EXISTS share_token TEXT;   -- the compiled package's public link

-- Public "Package Builder" page an agency publishes: a client picks their wishes
-- on a branded, no-account page and the agent mesh auto-drafts a full package.
CREATE TABLE IF NOT EXISTS package_pages (
    org_id     TEXT PRIMARY KEY,
    token      TEXT UNIQUE NOT NULL,
    org_name   TEXT,
    headline   TEXT,
    subhead    TEXT,
    enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Inbound conversations (WhatsApp/etc.): every message in/out of a lead thread,
-- so the console can show the chat and the AI's auto-replies.
CREATE TABLE IF NOT EXISTS inbox_messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      TEXT NOT NULL,
    channel     TEXT NOT NULL DEFAULT 'whatsapp',  -- whatsapp | telegram | web
    sender      TEXT NOT NULL,                      -- the lead's id/number
    sender_name TEXT,
    text        TEXT NOT NULL,
    direction   TEXT NOT NULL,                      -- in | out
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS inbox_org_sender_idx ON inbox_messages (org_id, sender, created_at);

CREATE TABLE IF NOT EXISTS shared_plans (
    token       TEXT PRIMARY KEY,
    org_id      UUID REFERENCES organizations(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT 'Your Trip',
    snapshot    JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Hotel property ops (Track B): bookings + a single finance ledger.
-- A consumer books a direct room -> the firewall guards it -> a booking is
-- recorded -> an income transaction posts to finance -> the manager is
-- notified. Refunds (from the escrow adjudicator) post here too, so one page
-- shows every money movement with a receipt per transaction.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hotel_bookings (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    listing_id    UUID REFERENCES supplier_listings(id) ON DELETE SET NULL,
    property_name TEXT,
    room_title    TEXT,
    guest_name    TEXT NOT NULL,
    guest_contact TEXT,
    channel       TEXT NOT NULL DEFAULT 'journava',
    check_in      DATE,
    check_out     DATE,
    nights        INTEGER NOT NULL DEFAULT 1,
    amount        NUMERIC(12,2) NOT NULL DEFAULT 0,
    currency      TEXT NOT NULL DEFAULT 'MYR',
    status        TEXT NOT NULL DEFAULT 'confirmed',  -- confirmed | checked_in | completed | cancelled
    reminded_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS hotel_bookings_org_idx ON hotel_bookings (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS hotel_bookings_checkin_idx ON hotel_bookings (org_id, check_in);
ALTER TABLE hotel_bookings ADD COLUMN IF NOT EXISTS reminded_at TIMESTAMPTZ;
-- Simulated payment for the public direct-booking site (no real gateway).
ALTER TABLE hotel_bookings ADD COLUMN IF NOT EXISTS payment_status TEXT NOT NULL DEFAULT 'unpaid';  -- unpaid | paid | refunded
ALTER TABLE hotel_bookings ADD COLUMN IF NOT EXISTS payment_ref TEXT;
ALTER TABLE agency_clients ADD COLUMN IF NOT EXISTS whatsapp TEXT;
ALTER TABLE agency_clients ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'telegram';

-- Saved research results — a traveller keeps any result (flights / places /
-- full trip) to revisit or re-run later, shown in Research → Saved results.
CREATE TABLE IF NOT EXISTS saved_results (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    scope       TEXT NOT NULL DEFAULT 'full_trip',
    kind        TEXT NOT NULL DEFAULT 'result',  -- result | trip (confirmed)
    title       TEXT NOT NULL DEFAULT 'Saved result',
    destination TEXT,
    snapshot    JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS saved_results_user_idx ON saved_results (user_id, created_at DESC);

-- Trip collaboration: the author of a saved trip invites people (by email) to
-- view or edit it. A row links (once they exist) to a user; until then it waits
-- on the email so an invite sent before signup still lands when they register.
CREATE TABLE IF NOT EXISTS trip_collaborators (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    saved_id    UUID NOT NULL REFERENCES saved_results(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,                    -- invited email (lowercased)
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    role        TEXT NOT NULL DEFAULT 'viewer',   -- viewer | editor
    status      TEXT NOT NULL DEFAULT 'invited',  -- invited | accepted
    invited_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (saved_id, email)
);
CREATE INDEX IF NOT EXISTS trip_collab_user_idx ON trip_collaborators (user_id);
CREATE INDEX IF NOT EXISTS trip_collab_saved_idx ON trip_collaborators (saved_id);

-- Agent Studio: plug-and-play role agents a business (hotel/agency) creates at
-- runtime. The owner describes a role in plain language; a meta-agent drafts the
-- identity + system prompt + skills + tools, and a generic executor runs it
-- (LLM + optional live web research). Org-scoped; no code deploy.
CREATE TABLE IF NOT EXISTS custom_agents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        TEXT NOT NULL,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,
    tagline       TEXT,
    emoji         TEXT,
    system_prompt TEXT NOT NULL,
    skills        JSONB NOT NULL DEFAULT '[]'::jsonb,
    tools         JSONB NOT NULL DEFAULT '[]'::jsonb,
    runs          INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS custom_agents_org_idx ON custom_agents (org_id, created_at DESC);

-- Knowledge Base: the business's own facts (brochure text, policies, a website)
-- that ground every custom agent + the inbox so they answer accurately about
-- THIS business. Lightweight keyword retrieval over these rows — no vector DB.
CREATE TABLE IF NOT EXISTS kb_entries (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     TEXT NOT NULL,
    title      TEXT NOT NULL,
    source     TEXT,                 -- url | text
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS kb_org_idx ON kb_entries (org_id, created_at DESC);
ALTER TABLE saved_results ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'result';
-- When a proactive trip notification (e.g. a countdown) was last sent, so the
-- reminder loop pings each trip once instead of every cycle.
ALTER TABLE saved_results ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;
-- The calendar date the "what to do today" digest last went out for this trip,
-- so it fires once per day regardless of how often the reminder loop runs.
ALTER TABLE saved_results ADD COLUMN IF NOT EXISTS last_digest_on DATE;

-- Price-drop autopilot: a traveller arms a watch on a fare; a background sweep
-- re-prices it and, when it drops past the threshold, notifies (and, if armed,
-- auto-rebooks). notified_at dedupes so each drop fires a single alert.
CREATE TABLE IF NOT EXISTS fare_watches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    origin          TEXT NOT NULL,
    destination     TEXT NOT NULL,
    depart_date     TEXT,
    travellers      INTEGER NOT NULL DEFAULT 1,
    baseline_amount NUMERIC NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'MYR',
    threshold_pct   INTEGER NOT NULL DEFAULT 10,
    auto_rebook     BOOLEAN NOT NULL DEFAULT false,
    budget_amount   NUMERIC,
    last_amount     NUMERIC,
    status          TEXT NOT NULL DEFAULT 'active',  -- active | triggered | rebooked
    last_checked_at TIMESTAMPTZ,
    notified_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fare_watches_user_idx ON fare_watches (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS fare_watches_active_idx ON fare_watches (status) WHERE status = 'active';

-- Collaborative voting: friends vote on a shared plan's places by its public
-- token. UNIQUE(token,item,voter) makes a vote idempotent (toggle).
CREATE TABLE IF NOT EXISTS plan_votes (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token      TEXT NOT NULL,
    item       TEXT NOT NULL,
    voter      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (token, item, voter)
);
CREATE INDEX IF NOT EXISTS plan_votes_token_idx ON plan_votes (token);

-- Group expense split: shared trip costs + who-owes-whom settle-up. Scoped to
-- the trip owner (user_id) and grouped within a trip by trip_key.
CREATE TABLE IF NOT EXISTS trip_expenses (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    trip_key    TEXT NOT NULL,
    description TEXT NOT NULL,
    amount      NUMERIC NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'MYR',
    paid_by     TEXT NOT NULL,
    shared_by   JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS trip_expenses_key_idx ON trip_expenses (user_id, trip_key, created_at);

CREATE TABLE IF NOT EXISTS finance_transactions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,                 -- income | refund | payout | fee | adjustment
    amount       NUMERIC(12,2) NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'MYR',
    status       TEXT NOT NULL DEFAULT 'completed', -- completed | pending | failed
    reference    TEXT,                          -- booking id, escrow hold id, order no
    counterparty TEXT,                          -- guest / traveller / channel
    description  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS finance_tx_org_idx ON finance_transactions (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS finance_tx_kind_idx ON finance_transactions (org_id, kind);
