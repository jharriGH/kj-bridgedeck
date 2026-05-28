-- Phase G Day 1 — Cost Guard schema bootstrap
-- Target project: dhzpwobfihrprlcxqjbq
-- Schema: cost_guard (isolated from all other empire schemas)
-- RLS: disabled (service-role-only access)
-- Reversible: DROP SCHEMA cost_guard CASCADE;

BEGIN;

CREATE SCHEMA cost_guard;

-- =====================================================================
-- TABLE 1: cost_guard.providers
-- Registry of every cost-bearing external service in the empire.
-- =====================================================================
CREATE TABLE cost_guard.providers (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                 text UNIQUE NOT NULL,
    display_name         text NOT NULL,
    billing_model        text NOT NULL CHECK (billing_model IN ('usage','subscription','hybrid')),
    api_balance_endpoint text,
    daily_cap_usd        numeric(10,2) DEFAULT 0,
    monthly_cap_usd      numeric(10,2) DEFAULT 0,
    soft_warning_mode    boolean DEFAULT true,
    created_at           timestamptz DEFAULT now(),
    updated_at           timestamptz DEFAULT now()
);
CREATE INDEX idx_cost_guard_providers_slug ON cost_guard.providers(slug);

-- =====================================================================
-- TABLE 2: cost_guard.daily_spend
-- One row per provider per day. Populated by G1 daily fetcher.
-- =====================================================================
CREATE TABLE cost_guard.daily_spend (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id   uuid NOT NULL REFERENCES cost_guard.providers(id) ON DELETE CASCADE,
    spend_date    date NOT NULL,
    amount_usd    numeric(10,4) NOT NULL DEFAULT 0,
    source        text NOT NULL CHECK (source IN ('api_pull','invoice_parse','estimated','manual')),
    raw_response  jsonb,
    fetched_at    timestamptz DEFAULT now(),
    CONSTRAINT uq_cost_guard_daily_spend_provider_date UNIQUE (provider_id, spend_date)
);
CREATE INDEX idx_cost_guard_daily_spend_date ON cost_guard.daily_spend(spend_date DESC);

-- =====================================================================
-- TABLE 3: cost_guard.cost_events
-- Per-request cost attribution. BridgeDeck writes here on every billable
-- provider call. Replaces ad-hoc per-product cost_log tables.
-- =====================================================================
CREATE TABLE cost_guard.cost_events (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id   uuid NOT NULL REFERENCES cost_guard.providers(id) ON DELETE RESTRICT,
    product_slug  text NOT NULL,
    event_type    text NOT NULL,
    amount_usd    numeric(10,6) NOT NULL,
    quantity      numeric DEFAULT 1,
    metadata      jsonb DEFAULT '{}'::jsonb,
    created_at    timestamptz DEFAULT now()
);
CREATE INDEX idx_cost_guard_cost_events_provider_created ON cost_guard.cost_events(provider_id, created_at DESC);
CREATE INDEX idx_cost_guard_cost_events_product_created  ON cost_guard.cost_events(product_slug, created_at DESC);
CREATE INDEX idx_cost_guard_cost_events_created          ON cost_guard.cost_events(created_at DESC);

-- =====================================================================
-- TABLE 4: cost_guard.caps_state
-- Live state of caps per provider. One row per provider, updated by
-- triggers plus nightly job. G2 reads this to decide block-or-warn.
-- =====================================================================
CREATE TABLE cost_guard.caps_state (
    provider_id          uuid PRIMARY KEY REFERENCES cost_guard.providers(id) ON DELETE CASCADE,
    today_spend_usd      numeric(10,4) DEFAULT 0,
    month_spend_usd      numeric(10,4) DEFAULT 0,
    daily_cap_status     text NOT NULL DEFAULT 'ok'   CHECK (daily_cap_status   IN ('ok','warning','exceeded')),
    monthly_cap_status   text NOT NULL DEFAULT 'ok'   CHECK (monthly_cap_status IN ('ok','warning','exceeded')),
    last_recalc_at       timestamptz DEFAULT now()
);

-- =====================================================================
-- TABLE 5: cost_guard.cap_violations
-- Audit trail of every cap breach. G2 inserts here on every
-- soft-warning or hard-block decision.
-- =====================================================================
CREATE TABLE cost_guard.cap_violations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id     uuid NOT NULL REFERENCES cost_guard.providers(id) ON DELETE CASCADE,
    violation_type  text NOT NULL CHECK (violation_type IN ('daily_warning','daily_exceeded','monthly_warning','monthly_exceeded')),
    cap_usd         numeric(10,2) NOT NULL,
    actual_usd      numeric(10,4) NOT NULL,
    product_slug    text,
    action_taken    text NOT NULL CHECK (action_taken IN ('warn_only','blocked','override_allowed')),
    created_at      timestamptz DEFAULT now()
);
CREATE INDEX idx_cost_guard_cap_violations_provider_created ON cost_guard.cap_violations(provider_id, created_at DESC);

-- =====================================================================
-- TABLE 6: cost_guard.anomaly_alerts
-- G4 anomaly detection writes here when daily spend exceeds 3x the
-- rolling 14-day avg.
-- =====================================================================
CREATE TABLE cost_guard.anomaly_alerts (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id       uuid NOT NULL REFERENCES cost_guard.providers(id) ON DELETE CASCADE,
    spend_date        date NOT NULL,
    actual_usd        numeric(10,4) NOT NULL,
    rolling_avg_usd   numeric(10,4) NOT NULL,
    multiplier        numeric(10,2) NOT NULL,
    alert_sent        boolean DEFAULT false,
    acknowledged_at   timestamptz,
    created_at        timestamptz DEFAULT now()
);
CREATE INDEX idx_cost_guard_anomaly_alerts_provider_date ON cost_guard.anomaly_alerts(provider_id, spend_date DESC);

-- =====================================================================
-- SEED DATA: 10 known cost-bearing providers.
-- soft_warning_mode = true for first 14 days per Phase G v1.0 decision.
-- Caps all 0 initially; G2 dispatch populates real cap values.
-- =====================================================================
INSERT INTO cost_guard.providers (slug, display_name, billing_model, soft_warning_mode) VALUES
    ('outscraper', 'Outscraper', 'usage',        true),
    ('openai',     'OpenAI',     'usage',        true),
    ('anthropic',  'Anthropic',  'usage',        true),
    ('twilio',     'Twilio',     'usage',        true),
    ('resend',     'Resend',     'usage',        true),
    ('searchbug',  'Searchbug',  'usage',        true),
    ('render',     'Render',     'subscription', true),
    ('railway',    'Railway',    'subscription', true),
    ('supabase',   'Supabase',   'subscription', true),
    ('stripe',     'Stripe',     'hybrid',       true);

COMMIT;
