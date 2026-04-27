# KJ RULEZ — Standing Rules for All KJE Builds

> Empire-wide standards. Apply to every KJE / DevelopingRiches product build.
> Repo-specific rules live in each repo's `CLAUDE.md`. The rules below
> override conflicting per-repo guidance unless the per-repo file explicitly
> says "supersedes KJ_RULEZ".

---

## BRAIN ENDPOINT VERIFICATION RULE

Before any KJE product calls a new Brain endpoint, the build prompt MUST
include a smoke-test step.

The smoke-test step MUST include all of these:

1. **Hit `/health` first** to confirm Brain is reachable + version is current:

   ```bash
   curl -s https://jim-brain-production.up.railway.app/health
   ```

2. **Hit the exact endpoint you intend to call**, with the lowercase auth
   header:

   ```bash
   curl -s https://jim-brain-production.up.railway.app/[endpoint] \
     -H "x-brain-key: jim-brain-kje-2026-kingjames"
   ```

   IMPORTANT: header is `x-brain-key` (lowercase), NOT `Authorization: Bearer`
   or `X-API-Key`. This was burned in 2026-04-27 BridgeDeck debugging.

3. **Capture the actual JSON response shape** and document it in the build
   prompt:

   - Top-level keys
   - Whether arrays are wrapped (e.g. `{"projects":[...], "count":N}`) or naked
   - Field name mappings to local schema (e.g. `brain.id → local.slug`)
   - Pseudo-projects to filter (e.g. `{"id":"all"}` is a UI placeholder)

4. **WHAT COUNTS AS VERIFYING:**

   - Real curl output showing HTTP 200 + JSON body
   - Documented field mapping table
   - Explicit handling of pseudo/special rows

5. **WHAT DOES NOT COUNT:**

   - "It probably looks like..."
   - Assuming endpoint paths from convention (e.g. `/codedeck/X` when `/X` is
     real)
   - Reusing endpoints from prior product memory without re-verifying — Brain
     versions evolve

### Endpoint catalog (verified live 2026-04-27)

See `CLAUDE.md` in `kj-bridgedeck` for the full GET/POST/PATCH/DELETE
catalog. Until a project moves it elsewhere, treat that catalog as the
empire-wide canonical list and update it when Brain changes.

---

## REVISION LOG

- **2026-04-27**: Rule introduced after BridgeDeck Bridge-C burned ~2 hours
  debugging `/codedeck/projects` (didn't exist) + `Authorization: Bearer`
  (wrong header). Real endpoint was `/projects` with `x-brain-key` header.
  Both were guessable from convention but neither was verified against live
  Brain.
