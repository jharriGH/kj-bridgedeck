-- 2026-04-27 — Brain `/projects` returns extra fields (group, status,
-- next_action) that don't have first-class columns in `kjcodedeck.projects`.
-- Stash them in a JSONB blob so the sync upsert can persist them
-- without losing data. Existing rows get an empty `{}`.
--
-- Run in Supabase SQL Editor when convenient. The /projects/sync route
-- gracefully strips this field from the payload if the column doesn't
-- exist yet (sync will still succeed with the basic fields).

ALTER TABLE kjcodedeck.projects
  ADD COLUMN IF NOT EXISTS brain_extras JSONB DEFAULT '{}'::jsonb;

COMMENT ON COLUMN kjcodedeck.projects.brain_extras IS
  'Brain /projects fields that don''t map to dedicated columns: group, status, next_action.';
