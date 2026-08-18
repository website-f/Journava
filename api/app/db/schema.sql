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
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

-- LLM provider configuration (Phase 3: Engine management page).
-- The failover chain is determined by priority (lower = tried first).
CREATE TABLE IF NOT EXISTS llm_providers (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL UNIQUE,        -- "Groq", "OpenRouter", "DashScope", etc.
    litellm_model TEXT NOT NULL,               -- "groq/llama-3.3-70b-versatile"
    api_key       TEXT NOT NULL,               -- stored server-side only
    priority      INTEGER NOT NULL DEFAULT 0,  -- lower = tried first
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    max_rpm       INTEGER,                     -- optional rate-limit guard
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
