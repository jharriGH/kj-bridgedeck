-- 2026-04-28 — Empire-wide external billing ingestion
-- Pulls Anthropic + OpenAI org-level usage daily into Supabase so the Cost
-- tab shows BILLED truth (not just cost_log estimated truth).
--
-- Idempotent. Safe to re-run.

CREATE TABLE IF NOT EXISTS kjcodedeck.external_spend_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider        TEXT NOT NULL,             -- 'anthropic' | 'openai'
    billing_date    DATE NOT NULL,
    api_key_hint    TEXT,                      -- last 4 chars of key id used
    source_app      TEXT,                      -- if identifiable from key/workspace
    workspace_id    TEXT,                      -- Anthropic workspace if applicable
    model           TEXT,
    tokens_in       BIGINT DEFAULT 0,
    tokens_out      BIGINT DEFAULT 0,
    cache_read_tokens   BIGINT DEFAULT 0,
    cache_write_tokens  BIGINT DEFAULT 0,
    request_count   INTEGER DEFAULT 0,
    cost_usd        NUMERIC(12,6) NOT NULL,
    raw_response    JSONB,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(provider, billing_date, api_key_hint, model, workspace_id)
);

CREATE INDEX IF NOT EXISTS idx_external_billing_date
    ON kjcodedeck.external_spend_log(billing_date DESC);
CREATE INDEX IF NOT EXISTS idx_external_provider
    ON kjcodedeck.external_spend_log(provider, billing_date DESC);

-- View: empire-wide spend daily breakdown (last 30 days, both providers)
CREATE OR REPLACE VIEW kjcodedeck.empire_spend_30d AS
SELECT
    'anthropic' AS provider,
    billing_date,
    SUM(cost_usd)             AS daily_cost,
    SUM(tokens_in)            AS tokens_in,
    SUM(tokens_out)           AS tokens_out,
    SUM(cache_read_tokens)    AS cache_reads,
    COUNT(DISTINCT model)     AS models_used,
    COUNT(DISTINCT api_key_hint) AS keys_used
FROM kjcodedeck.external_spend_log
WHERE provider = 'anthropic'
  AND billing_date > CURRENT_DATE - INTERVAL '30 days'
GROUP BY billing_date

UNION ALL

SELECT
    'openai' AS provider,
    billing_date,
    SUM(cost_usd)             AS daily_cost,
    SUM(tokens_in)            AS tokens_in,
    SUM(tokens_out)           AS tokens_out,
    0                         AS cache_reads,
    COUNT(DISTINCT model)     AS models_used,
    COUNT(DISTINCT api_key_hint) AS keys_used
FROM kjcodedeck.external_spend_log
WHERE provider = 'openai'
  AND billing_date > CURRENT_DATE - INTERVAL '30 days'
GROUP BY billing_date

ORDER BY billing_date DESC, provider;

-- View: logged (cost_log) vs billed (external_spend_log) reconciliation, 7 days.
-- "Untracked cost" = Anthropic billed it but BridgeDeck cost_log missed it,
-- which usually means a KJE product is calling Anthropic without logging
-- through the BridgeDeck pipeline.
CREATE OR REPLACE VIEW kjcodedeck.spend_reconciliation_7d AS
WITH logged AS (
    SELECT DATE(created_at) AS date,
           SUM(cost_usd) AS logged_cost
    FROM kjcodedeck.cost_log
    WHERE created_at > NOW() - INTERVAL '7 days'
    GROUP BY DATE(created_at)
),
billed AS (
    SELECT billing_date AS date,
           SUM(cost_usd) AS billed_cost
    FROM kjcodedeck.external_spend_log
    WHERE provider = 'anthropic'
      AND billing_date > CURRENT_DATE - INTERVAL '7 days'
    GROUP BY billing_date
)
SELECT
    COALESCE(l.date, b.date)               AS date,
    COALESCE(l.logged_cost, 0)             AS logged_cost,
    COALESCE(b.billed_cost, 0)             AS billed_cost,
    COALESCE(b.billed_cost, 0) - COALESCE(l.logged_cost, 0) AS untracked_cost,
    CASE
        WHEN COALESCE(b.billed_cost, 0) = 0 THEN 100.0
        ELSE ROUND((COALESCE(l.logged_cost, 0) / b.billed_cost * 100)::numeric, 1)
    END AS coverage_pct
FROM logged l
FULL OUTER JOIN billed b USING (date)
ORDER BY date DESC;

ALTER TABLE kjcodedeck.external_spend_log ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "service_full_access" ON kjcodedeck.external_spend_log
        FOR ALL TO service_role USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

GRANT ALL    ON kjcodedeck.external_spend_log     TO service_role;
GRANT SELECT ON kjcodedeck.empire_spend_30d       TO service_role;
GRANT SELECT ON kjcodedeck.spend_reconciliation_7d TO service_role;
