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
    name          TEXT NOT NULL UNIQUE,        -- "Groq", "OpenRouter", "DashScope", etc.
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
