-- 2026-04-27 — Cost Intelligence Sprint
-- Adds two tables backing the empire-wide cost guardrails + UI dashboards:
--   kjcodedeck.cost_log   — every billable model call
--   kjcodedeck.cost_caps  — empire/project/per-turn spend ceilings
--
-- Idempotent. Safe to re-run.

CREATE TABLE IF NOT EXISTS kjcodedeck.cost_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_system    TEXT NOT NULL,         -- 'bridge', 'cc_session', 'summarizer', 'intent', 'whisper'
    project_slug     TEXT,
    session_id       TEXT,
    conversation_id  TEXT,
    turn_id          TEXT,
    model            TEXT,
    tokens_in        INTEGER DEFAULT 0,
    tokens_out       INTEGER DEFAULT 0,
    cost_usd         NUMERIC(10,6) NOT NULL,
    intent           TEXT,
    duration_ms      INTEGER,
    outcome_tag      TEXT,                  -- 'useful', 'partial', 'wasted'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cost_created ON kjcodedeck.cost_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cost_source  ON kjcodedeck.cost_log(source_system, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cost_project ON kjcodedeck.cost_log(project_slug, created_at DESC);

CREATE TABLE IF NOT EXISTS kjcodedeck.cost_caps (
    scope            TEXT PRIMARY KEY,      -- 'empire_daily', 'empire_weekly', 'project:{slug}_daily', 'bridge_per_turn'
    cap_usd          NUMERIC(8,2) NOT NULL,
    behavior         TEXT DEFAULT 'warn',   -- 'warn', 'haiku_force', 'hard_stop'
    enabled          BOOLEAN DEFAULT TRUE,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO kjcodedeck.cost_caps (scope, cap_usd, behavior) VALUES
    ('empire_daily',     10.00, 'warn'),
    ('empire_weekly',    50.00, 'haiku_force'),
    ('bridge_per_turn',   0.50, 'hard_stop')
ON CONFLICT (scope) DO NOTHING;

ALTER TABLE kjcodedeck.cost_log  ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.cost_caps ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "service_full_access" ON kjcodedeck.cost_log
        FOR ALL TO service_role USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE POLICY "service_full_access" ON kjcodedeck.cost_caps
        FOR ALL TO service_role USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
