-- Phase G Day 1 — Cost Guard schema bootstrap (code-only retry v2)
-- Target project: dhzpwobfihrprlcxqjbq
-- Schema: cost_guard (isolated from all other empire schemas)
-- Reversible: DROP SCHEMA cost_guard CASCADE;
--
-- This migration is intended to be applied manually via the Supabase
-- SQL editor. See supabase/migrations/PHASE_G_APPLICATION.md for the
-- application order and verification steps.

BEGIN;

CREATE SCHEMA IF NOT EXISTS cost_guard;

-- =====================================================================
-- TABLE 1: cost_guard.providers
-- Registry of every cost-bearing external service in the empire.
-- =====================================================================
CREATE TABLE IF NOT EXISTS cost_guard.providers (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                 text UNIQUE NOT NULL,
    display_name         text NOT NULL,
    category             text NOT NULL,
    api_balance_endpoint text,
    has_balance_api      boolean NOT NULL DEFAULT false,
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cost_guard_providers_slug
    ON cost_guard.providers(slug);

-- =====================================================================
-- TABLE 2: cost_guard.daily_spend
-- One row per provider per day. Populated by the G1 daily fetcher.
-- =====================================================================
CREATE TABLE IF NOT EXISTS cost_guard.daily_spend (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id   uuid NOT NULL REFERENCES cost_guard.providers(id) ON DELETE CASCADE,
    date          date NOT NULL,
    amount_usd    numeric(12,4) NOT NULL DEFAULT 0,
    source        text NOT NULL CHECK (source IN ('api_pull','manual')),
    raw_response  jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_cost_guard_daily_spend_provider_date UNIQUE (provider_id, date)
);
CREATE INDEX IF NOT EXISTS idx_cost_guard_daily_spend_date
    ON cost_guard.daily_spend(date DESC);

-- =====================================================================
-- TABLE 3: cost_guard.daily_caps
-- Active spend caps per provider, with a warning threshold expressed
-- as a percentage of the cap.
-- =====================================================================
CREATE TABLE IF NOT EXISTS cost_guard.daily_caps (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id            uuid NOT NULL REFERENCES cost_guard.providers(id) ON DELETE CASCADE,
    cap_usd                numeric(12,4) NOT NULL,
    warning_threshold_pct  numeric(5,2)  NOT NULL DEFAULT 80.0,
    is_active              boolean       NOT NULL DEFAULT true,
    created_at             timestamptz   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cost_guard_daily_caps_provider_active
    ON cost_guard.daily_caps(provider_id, is_active);

-- =====================================================================
-- TABLE 4: cost_guard.spend_alerts
-- Audit trail of every warning, critical, or breach event raised
-- against a daily cap.
-- =====================================================================
CREATE TABLE IF NOT EXISTS cost_guard.spend_alerts (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id  uuid NOT NULL REFERENCES cost_guard.providers(id) ON DELETE CASCADE,
    date         date NOT NULL,
    alert_level  text NOT NULL CHECK (alert_level IN ('warning','critical','breach')),
    amount_usd   numeric(12,4) NOT NULL,
    cap_usd      numeric(12,4) NOT NULL,
    message      text,
    resolved     boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cost_guard_spend_alerts_provider_date
    ON cost_guard.spend_alerts(provider_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_cost_guard_spend_alerts_unresolved
    ON cost_guard.spend_alerts(resolved, created_at DESC);

-- =====================================================================
-- TABLE 5: cost_guard.attribution_rules
-- Allocates a provider's spend across products by percentage, with an
-- effective-date window.
-- =====================================================================
CREATE TABLE IF NOT EXISTS cost_guard.attribution_rules (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id     uuid NOT NULL REFERENCES cost_guard.providers(id) ON DELETE CASCADE,
    product_slug    text NOT NULL,
    allocation_pct  numeric(5,2) NOT NULL,
    effective_from  date NOT NULL,
    effective_to    date,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cost_guard_attribution_rules_provider_window
    ON cost_guard.attribution_rules(provider_id, effective_from, effective_to);

-- =====================================================================
-- TABLE 6: cost_guard.audit_log
-- Generic audit trail for cost_guard events that do not fit the more
-- specialized tables above.
-- =====================================================================
CREATE TABLE IF NOT EXISTS cost_guard.audit_log (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type   text NOT NULL,
    provider_id  uuid REFERENCES cost_guard.providers(id) ON DELETE SET NULL,
    payload      jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cost_guard_audit_log_event_created
    ON cost_guard.audit_log(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cost_guard_audit_log_provider_created
    ON cost_guard.audit_log(provider_id, created_at DESC);

COMMIT;
