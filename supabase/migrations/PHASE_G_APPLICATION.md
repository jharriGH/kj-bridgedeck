# Phase G — Cost Guard schema: manual application

This pair of migration files creates the `cost_guard` schema in Supabase
project `dhzpwobfihrprlcxqjbq`. Apply them by hand via the Supabase SQL
editor — no migration tool is invoked from the repo, and the prior
auto-apply dispatch (session `b3be3e31`) is known to have failed
silently, which is why this retry is code-only.

## Files

In `supabase/migrations/`, apply in the order shown by their
timestamp prefix:

1. `20260528024121_create_cost_guard_schema.sql`
   Creates `cost_guard` schema plus 6 tables: `providers`,
   `daily_spend`, `daily_caps`, `spend_alerts`, `attribution_rules`,
   `audit_log`. Wrapped in a single transaction.

2. `20260528024122_seed_cost_guard_providers.sql`
   Inserts 10 provider rows (outscraper, openai, anthropic, twilio,
   resend, searchbug, render, railway, supabase, stripe). Idempotent
   via `ON CONFLICT (slug) DO NOTHING`.

## How to apply

1. Open the Supabase SQL editor for project `dhzpwobfihrprlcxqjbq`.
2. Paste the contents of file (1) and run.
3. Paste the contents of file (2) and run.

## Verification

After both files run cleanly, confirm the seed is present:

```sql
SELECT count(*) FROM cost_guard.providers;
-- Expected: 10
```

You can also sanity-check the table set:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'cost_guard'
ORDER BY table_name;
-- Expected: attribution_rules, audit_log, daily_caps,
--           daily_spend, providers, spend_alerts
```

## Rollback

The schema is isolated; to undo, run:

```sql
DROP SCHEMA cost_guard CASCADE;
```
