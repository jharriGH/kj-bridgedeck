---
## AUTONOMOUS EXECUTION — READ THIS FIRST

You are part of the King James Empire CC fleet.
Jim Harris is NEVER the middleman. Ever.

BEFORE ANYTHING ELSE:
brain_session_start(focus="[task]", product="[project]")

GET CREDENTIALS (never ask Jim):
brain_vault_search("what you need")

DISPATCH ANOTHER CC (never ask Jim to do it):
run_build_task(project="[project]", prompt="[task]")

LOG EVERYTHING:
brain_log(content, project)     — events
brain_memory(content, tags)     — decisions

END EVERY SESSION:
brain_session_end(product, what_shipped,
  decisions, next_action)
brain_save_card(title, project, content)

ONLY INTERRUPT JIM FOR:
+ Business decisions requiring his judgment
+ Credentials genuinely not in vault after search
+ Task complete — here are the results
+ Truly blocked with specific reason

NEVER:
- Ask Jim for credentials
- Ask Jim to copy/paste anything
- Present options and wait
- Ask Jim to run any command
- Be the middleman between SC and CC

KJE MCP: https://kje-mcp.onrender.com/mcp/T24NM1Sxbh7txJs-unNIjblaXMqA1OZW6gNU-Ud5Yjk/
VPS: 192.161.173.97 (claude at /usr/local/bin/claude)
Brain: https://jim-brain-production.up.railway.app
Key: jim-brain-kje-2026-kingjames
---

---
## MANDATORY: START EVERY SESSION WITH THIS
brain_session_start(
  focus="[describe what you are working on]",
  product="[this repo's project id]"
)
Brain URL: https://jim-brain-production.up.railway.app
Brain Key: jim-brain-kje-2026-kingjames
DO THIS BEFORE ANY OTHER WORK. NO EXCEPTIONS.
---

# KJ BridgeDeck — Empire Context

**Product:** KJ BridgeDeck — visual terminal management + voice-first empire command interface
**Owner:** Jim Harris / DevelopingRiches Inc (Long Beach, CA)
**Status:** In active development (Bridge-A/B/C/D/E parallel build)

## Brain Integration Contract

- Brain API: `https://jim-brain-production.up.railway.app` (v1.4.0)
- Brain key: `jim-brain-kje-2026-kingjames`
- Primary integration: `POST /codedeck/handoff`
- Memory flush cron: every 30 min via `install/brain_flush.ps1`
- Context injection: `GET /codedeck/context/{slug}?depth=standard`
- Review queue: low-confidence handoffs (<0.85) auto-flagged

## Key IDs

- Supabase project: `dhzpwobfihrprlcxqjbq`
- Supabase schema: `kjcodedeck`
- Render service: `kj-bridgedeck-api`
- Repo: `jharriGH/kj-bridgedeck`
- Agent ID (for Brain handoffs): `codedeck_watcher`

## Critical Rules

1. **Never write directly to Empire Context, empire_state, or Qdrant.** Always route through Brain API.
2. **Every DB write must also write a `history_log` entry.** Audit trail is non-negotiable.
3. **All configuration lives in `kjcodedeck.settings`.** No hardcoded values — read from settings at startup and on reload.
4. **Poll Claude Code process list every 3 sec.** Do **not** use watchdog/file-watchers on Windows (unreliable on the `\\wsl$` UNC path).
5. **All agents import from `shared/contracts.py` and `shared/contracts.ts`.** No duplicate type definitions.
6. **Dual-path Claude Code support.** Watcher must read both `C:\Users\Jim\.claude` (native Windows) and `\\wsl$\Ubuntu\home\jim\.claude` (WSL2).
7. **Windows-first.** WSL2 Ubuntu is available but UI, watcher, and installer all target Windows 11.

## Brain Endpoint Verification (MANDATORY)

BEFORE calling any Brain endpoint:

1. `curl https://jim-brain-production.up.railway.app/health` → confirm version
2. `curl <exact endpoint>` → confirm 200 before building any code that depends on it
3. Log the actual response shape into the session notes

**Never assume an endpoint exists. Always verify.**

### Brain v1.4.0 confirmed endpoints

GET endpoints:
- `/health`
- `/context`
- `/projects`                              ← project list, response: `{"projects":[...], "count":N}`
- `/cards`
- `/logs`
- `/memory/search`
- `/memory/all`
- `/cards/{id}`
- `/codedeck/review-queue`
- `/codedeck/context/{project_slug}`

POST endpoints:
- `/state`
- `/memory`
- `/log`
- `/cards`
- `/codedeck/handoff`
- `/codedeck/flush-memory-queue`
- `/codedeck/approve-review/{index}`

PATCH endpoints:
- `/state`
- `/projects`
- `/agents`

DELETE endpoints:
- `/cards/{id}`
- `/codedeck/review-queue/{index}`

### Brain field mapping for projects

When syncing from `/projects`:

- `brain["id"]`    → `kjcodedeck.projects.slug`
- `brain["label"]` → `kjcodedeck.projects.display_name`
- `brain["desc"]`  → `kjcodedeck.projects.description`
- `emoji`, `color`, `group`, `status`, `next_action`: as-is
- Skip the `{"id":"all"}` pseudo-project — it's a UI placeholder

## Agent boundaries (parallel build)

- **Bridge-A** — Schema + shared contracts + repo scaffold (foundation, runs first)
- **Bridge-B** — Windows watcher (Python) + tmux/Windows API control + local HTTP API on :7171
- **Bridge-C** — FastAPI service on Render + 40+ REST endpoints + Supabase proxy
- **Bridge-D** — Bridge chat core (Claude via API) + Piper TTS + Whisper STT + action executor
- **Bridge-E** — Standalone HTML/JS UI + deploy to Cloudflare Pages

## Communication patterns

- UI ↔ API (Render): HTTPS, Bearer token (`BRIDGEDECK_ADMIN_KEY`)
- API ↔ Watcher (localhost): HTTP on `:7171`, admin key header
- API ↔ Brain: HTTPS, `x-brain-key` header
- Watcher ↔ Supabase: Postgres write via service-role key
- UI ↔ Supabase: Read-only (via API proxy only — UI never calls Supabase directly)

## Quick-reference commands

```bash
# Run watcher locally (Bridge-B)
cd watcher && python -m bridgedeck_watcher

# Run API locally (Bridge-C)
cd api && uvicorn main:app --reload --port 8000

# Start UI dev server (Bridge-E)
cd bridge-ui && npm run dev

# Flush Brain queue manually
pwsh install/brain_flush.ps1
```

## Empire credentials — persistent storage

All platform tokens for env var automation live at:

    %USERPROFILE%\.kje\secrets.env

Currently stored:
- `RENDER_API_KEY`  (set 2026-05-07) — manages all Render services
- `RAILWAY_TOKEN`   (pending — set when first Railway env op needed)
- `CF_API_TOKEN`    (pending — set when first Cloudflare Pages env op needed)

Source of truth is Brain Vault under the `empire` project (e.g.
`empire/RENDER_API_KEY`). The local file is a session-bootstrap
convenience so CC sessions don't need to re-fetch from vault on every
launch.

To load all empire credentials into the current PowerShell session:

```powershell
Get-Content $env:USERPROFILE\.kje\secrets.env | ForEach-Object {
    if ($_ -match '^([^=#]+)=(.*)$') {
        Set-Item -Path "env:$($matches[1])" -Value $matches[2]
    }
}
```

Bash equivalent:

```bash
set -a && source "$USERPROFILE/.kje/secrets.env" && set +a
```

`secrets.env` is OUTSIDE the repo and must never be committed.
