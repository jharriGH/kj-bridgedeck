-- Phase G Day 1 — Cost Guard provider seed (code-only retry v2)
-- Seeds 10 known cost-bearing providers into cost_guard.providers.
-- has_balance_api reflects publicly available balance/usage endpoints
-- (or, for railway and searchbug, vault-credentialed access).
--
-- Idempotent: ON CONFLICT (slug) DO NOTHING. Safe to re-run after
-- applying 20260528024121_create_cost_guard_schema.sql.

BEGIN;

INSERT INTO cost_guard.providers (slug, display_name, category, has_balance_api) VALUES
    ('outscraper', 'Outscraper', 'scraping',  true),
    ('openai',     'OpenAI',     'ai',        true),
    ('anthropic',  'Anthropic',  'ai',        false),
    ('twilio',     'Twilio',     'messaging', true),
    ('resend',     'Resend',     'messaging', false),
    ('searchbug',  'Searchbug',  'data',      true),
    ('render',     'Render',     'hosting',   true),
    ('railway',    'Railway',    'hosting',   true),
    ('supabase',   'Supabase',   'hosting',   false),
    ('stripe',     'Stripe',     'payments',  true)
ON CONFLICT (slug) DO NOTHING;

COMMIT;
