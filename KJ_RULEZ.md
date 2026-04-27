# KJ RULEZ — Standing Rules for All KJE Builds

> Empire-wide standards. Apply to every KJE / DevelopingRiches product build.
> Repo-specific rules live in each repo's `CLAUDE.md`. The rules below
> override conflicting per-repo guidance unless the per-repo file explicitly
> says "supersedes KJ_RULEZ".

---

## BRAIN ENDPOINT VERIFICATION RULE

Before any KJE product calls a new Brain endpoint, the build prompt MUST
include a smoke-test step. **No exceptions, no assumptions, no "probably
works".**

### The mandatory smoke-test sequence

Every build/agent that integrates with Brain runs these BEFORE writing
client code:

```bash
# 1. Confirm Brain is reachable and capture the version.
curl -sS https://jim-brain-production.up.railway.app/health
# expect: {"status":"ok","service":"Jim Brain API","version":"1.x.x", ...}

# 2. Confirm the EXACT endpoint you're about to call returns 200.
curl -sS -H "x-brain-key: jim-brain-kje-2026-kingjames" \
     https://jim-brain-production.up.railway.app/<endpoint>

# 3. Log the actual response shape (top-level keys, sample row) into the
#    session notes / handoff. This is what other agents read to know what
#    to map.
```

If any step fails or returns an unexpected shape, **STOP and surface the
discrepancy to the user before writing client code that assumes the
endpoint works.**

### What counts as "verifying"

- ✅ Curling the live Brain and inspecting the JSON response.
- ✅ Reading source for the deployed Brain build at the exact tag in
  production.
- ❌ "It's in the spec doc."
- ❌ "It worked in another repo last month."
- ❌ "The handoff template says it exists."

### Auth header

Brain v1.3.x and later require **`x-brain-key`** (lowercase). The legacy
`X-API-Key` and `Authorization: Bearer` headers are silently ignored.
Verified live 2026-04-27 against `jim-brain-production.up.railway.app`.

### Endpoint catalog (verified live 2026-04-27)

See `CLAUDE.md` in `kj-bridgedeck` for the full GET/POST/PATCH/DELETE
catalog. Until a project moves it elsewhere, treat that catalog as the
empire-wide canonical list and update it when Brain changes.

### Field-mapping discipline

Brain has its own field names; KJE products have their own. Map at the
boundary, never in the middle of business logic. Document the mapping in
`CLAUDE.md` next to the endpoint that uses it (see the
"Brain field mapping for projects" example).

### Skip pseudo-projects

`GET /projects` returns a `{"id":"all"}` placeholder for UI dropdowns.
Always filter it out before persisting to local Postgres / Supabase.

---

## REVISION LOG

- 2026-04-27 — initial rule introduced after a sync against
  `/codedeck/projects` 404'd because the endpoint was assumed, not
  verified. Real path is `/projects` with `{"projects":[...], "count":N}`.
