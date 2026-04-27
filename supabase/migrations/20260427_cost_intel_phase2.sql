-- 2026-04-27 — Cost Intelligence Phase 2
-- Builds on 20260427_cost_intel.sql. Adds:
--   * rate_limit_blocks  — audit log for Anthropic / Whisper 429 events
--   * turn_outcomes      — user-tagged 👍 / 👎 / 🗑 per Bridge turn
--   * 3 new bridge.* settings (cheap_mode, prompt_caching_enabled, auto_retry)
--   * 2 read-only views (cost_by_intent_30d, session_health_score)
--
-- Idempotent. Safe to re-run.

CREATE TABLE IF NOT EXISTS kjcodedeck.rate_limit_blocks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_provider    TEXT NOT NULL,           -- 'anthropic', 'openai_whisper'
    blocked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    requested_tokens INTEGER,
    current_usage   INTEGER,
    limit_value     INTEGER,
    queue_depth     INTEGER DEFAULT 0,
    resolved_at     TIMESTAMPTZ,
    resolution      TEXT                     -- 'queued_succeeded', 'timeout', 'cancelled'
);
CREATE INDEX IF NOT EXISTS idx_rate_limit_blocked_at
    ON kjcodedeck.rate_limit_blocks(blocked_at DESC);

CREATE TABLE IF NOT EXISTS kjcodedeck.turn_outcomes (
    turn_id         UUID PRIMARY KEY,
    conversation_id UUID NOT NULL,
    outcome         TEXT NOT NULL CHECK (outcome IN ('useful','partial','wasted','error_refund')),
    tagged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tagged_by       TEXT DEFAULT 'user'
);
CREATE INDEX IF NOT EXISTS idx_turn_outcomes_conv
    ON kjcodedeck.turn_outcomes(conversation_id, tagged_at DESC);

INSERT INTO kjcodedeck.settings (namespace, key, value, description) VALUES
    ('bridge', 'cheap_mode', 'false',
        'Global panic switch — force Haiku, minimal context, no TTS'),
    ('bridge', 'prompt_caching_enabled', 'true',
        'Anthropic prompt caching for stable system prompt blocks'),
    ('bridge', 'auto_retry_on_rate_limit', 'true',
        'Queue + auto-retry on rate limit instead of failing')
ON CONFLICT (namespace, key) DO NOTHING;

-- Per-intent cost rollup (last 30 days)
CREATE OR REPLACE VIEW kjcodedeck.cost_by_intent_30d AS
SELECT
    intent,
    COUNT(*)            AS turn_count,
    AVG(cost_usd)       AS avg_cost,
    SUM(cost_usd)       AS total_cost,
    AVG(tokens_in)      AS avg_in,
    AVG(tokens_out)     AS avg_out,
    AVG(duration_ms)    AS avg_ms
FROM kjcodedeck.cost_log
WHERE source_system = 'bridge'
  AND created_at > NOW() - INTERVAL '30 days'
  AND intent IS NOT NULL
GROUP BY intent
ORDER BY total_cost DESC;

-- Session health score (last 7 days)
CREATE OR REPLACE VIEW kjcodedeck.session_health_score AS
SELECT
    cl.session_id,
    cl.project_slug,
    SUM(cl.cost_usd)                                    AS total_cost,
    SUM(cl.tokens_in + cl.tokens_out)                   AS total_tokens,
    COUNT(*)                                            AS call_count,
    MAX(cl.created_at) - MIN(cl.created_at)             AS duration,
    COALESCE(sh.artifact_count, 0)                      AS artifacts_shipped,
    CASE
        WHEN COALESCE(sh.artifact_count, 0) = 0 AND SUM(cl.cost_usd) > 1.0  THEN 'thrashing'
        WHEN COALESCE(sh.artifact_count, 0) = 0 AND SUM(cl.cost_usd) > 0.25 THEN 'stuck'
        WHEN SUM(cl.cost_usd) / NULLIF(COALESCE(sh.artifact_count, 1), 0) > 2.0 THEN 'expensive'
        ELSE 'healthy'
    END AS health_status
FROM kjcodedeck.cost_log cl
LEFT JOIN (
    SELECT session_id, jsonb_array_length(artifacts) AS artifact_count
    FROM kjcodedeck.session_handoffs
) sh USING (session_id)
WHERE cl.source_system IN ('cc_session', 'summarizer')
  AND cl.session_id IS NOT NULL
  AND cl.created_at > NOW() - INTERVAL '7 days'
GROUP BY cl.session_id, cl.project_slug, sh.artifact_count;

ALTER TABLE kjcodedeck.rate_limit_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.turn_outcomes     ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    CREATE POLICY "service_full_access" ON kjcodedeck.rate_limit_blocks
        FOR ALL TO service_role USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE POLICY "service_full_access" ON kjcodedeck.turn_outcomes
        FOR ALL TO service_role USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
