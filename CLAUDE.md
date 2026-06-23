## 👑 Empire onboarding — read every session
Single source of truth: jharriGH/kjle. On session start, fetch + follow:
- https://raw.githubusercontent.com/jharriGH/kjle/main/EMPIRE_SC_HANDOFF.md
- https://raw.githubusercontent.com/jharriGH/kjle/main/EMPIRE_INTEGRATION_STANDARD.md

Keep current at this repo root:
1. ROADMAP.md — valid YAML front-matter (project, status, description, last_updated, repo,
   api_url, facts_doc, vault_key, integrates_with). The empire dashboard reads this; bump
   last_updated on any change.
2. PROJECT_FACTS.md — the integration contract (endpoints, schema, auth), verified against
   the live system. Vault key NAMES only — never secret values.
To learn about another project: brain_search("<project> integration") or read EMPIRE_INDEX.md
in jharriGH/kjle -> that repo's PROJECT_FACTS.md -> brain_vault_search for its key.
Repo edits: this repo only, explicit paths, never `git add -A`.


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

# ═══════════════════════════════════════════════════════════
#  KING JAMES EMPIRE — SC / CC OPERATING INSTRUCTIONS
#  Read first, every session. This is the single source of truth.
# ═══════════════════════════════════════════════════════════

## IDENTITY
I am Jim Harris, King James Empire, Long Beach CA. DevelopingRiches Inc (C-Corp). Solo founder.
Standard: GOAT — production-ready, no half-measures.
Doctrine: decide-and-proceed, but VERIFY LIVE — never trust a self-report.

# ───────────────────────────────────────────────────────────
# 0. EXECUTION & COST — HIGHEST AUTHORITY (overrides everything below)
# ───────────────────────────────────────────────────────────
Before ANY build task, STATE these three, then STOP for Jim's explicit "go":
1. Cheapest path. DEFAULT = a terminal-ready prompt Jim runs on his Max plan (~$0 marginal).
   Only name run_build_task if a local terminal genuinely can't do it (must run
   unattended/overnight, or on the VPS) — and say WHY.
2. Model + one-line reason. Default Sonnet; Opus only if earned.
3. Rough cost: ~$0 (Jim's terminal) vs ~$2-3 (metered dispatch).
NEVER fire run_build_task without Jim's explicit "go."

COST REALITY:
- run_build_task / kje-cc-dispatch = METERED API key (~$2-3 each, hourly invoices).
- Jim's local terminals = Max subscription, flat fee = the cheap path. Default to it.
- FREE tools (use automatically, no permission needed): brain_status, brain_search,
  brain_get_project, brain_vault_search, brain_log, brain_memory, vps_exec, curl, /logs.
- ONLY run_build_task costs money and needs Jim's go. Diagnostics are free — use freely.

# ───────────────────────────────────────────────────────────
# 1. MODEL TIERING
# ───────────────────────────────────────────────────────────
- Haiku 4.5  — trivial/mechanical (lookups, simple edits)
- Sonnet 4.6 — DEFAULT for real build work
- Opus 4.8   — only when the task earns it (hard reasoning/architecture). Sparingly.
- Dispatcher default model = claude-sonnet-4-6. NEVER spawn `claude -p` without an explicit
  --model AND --max-turns (an env-var default alone is not enough — pin it in the command).
- Prompt caching is automatic in Claude Code — keep context stable to maximize it.

# ───────────────────────────────────────────────────────────
# 2. GIT SAFETY
# ───────────────────────────────────────────────────────────
- Normal push only: `git push origin main`. `git push --force` is BANNED empire-wide.
  A push-rejected error is the safety net — never override it.
- Resolve conflicts by KEEPING BOTH SIDES (never --ours, which drops other SCs' work).
  CLAUDE.md is brain_sync-auto-generated, so --theirs is safe for THAT file only.
- Jim sees the exact unified diff before any file change is approved.

# ───────────────────────────────────────────────────────────
# 3. CREDENTIALS
# ───────────────────────────────────────────────────────────
- The vault holds most keys: brain_vault_search or GET /vault/{project}. Use them first.
- If a key is genuinely missing, or a NEW secret must be created (e.g. issuing a fresh API
  key), ASK JIM. Never guess, never fabricate, never paste a placeholder.

# ───────────────────────────────────────────────────────────
# 4. TERMINAL PROMPT SKELETON (what to hand Jim)
# ───────────────────────────────────────────────────────────
Fill this in and hand Jim the COMPLETED version — never leave <...> placeholders in a
prompt a CC actually receives:

Model: Sonnet (Haiku if trivial / Opus if flagged)
Repo + exact files: <repo + specific file paths>
Task: <one specific, bounded task>
Rules: minimal diff · don't explore beyond the named files · stop when done
Report: unified diff + one-line summary

# ───────────────────────────────────────────────────────────
# 5. BRAIN TOOLS — which when (+ gotchas)
# ───────────────────────────────────────────────────────────
- brain_memory → SEARCHABLE (mem0/Qdrant). Decisions, state, milestones, gotchas.
  Retry on 500; do NOT fall back to /log.
- brain_log → AUDIT ONLY (Supabase empire_logs), not searchable. Read via /logs?limit=N.
- brain_search → RECENCY-BLIND (ranks relevance, not freshness). Check created_at/age_days.
  <0.45 = noise; 0.65+ = real. ~30-min embedding lag — not for confirming recent work.
- Real-time "what just happened" → GET /logs?limit=N, never brain_search.
- Vault existence checks → GET /vault/{project}; brain_vault_search is loose-ranked.
- mem0 dedup can NOOP silently (success:true but nothing embedded) — for critical state,
  also write a deterministic record (build card / next_action), don't rely on search alone.
- "Tool not found" on a brain_* tool = stale MCP session after a kje-mcp (Render) restart →
  reconnect / fresh session, then retry.

# ───────────────────────────────────────────────────────────
# 6. DEPLOY-AND-VERIFY
# ───────────────────────────────────────────────────────────
- Detect a live deploy by polling a NEWLY-ADDED endpoint (200 = new code, 404 = old) —
  NOT /health 200 (it serves the old container during a 7-15 min build).
- Never combine push + verify in one dispatch. Never add auto-rollback timers.

# ───────────────────────────────────────────────────────────
# 7. SPEED & PARALLELISM (Jim's default preference)
# ───────────────────────────────────────────────────────────
- Move as FAST as safely possible — bias toward shipping. PROACTIVELY offer to split
  independent work into separate prompts Jim runs in parallel local terminals (Max plan =
  flat fee, so parallel = faster at ~$0 extra). Offer the parallel breakdown by default.
- Parallelize across DIFFERENT repos/files only — never parallel sessions on the same files
  (merge conflicts). If work is genuinely sequential, say so.
- "When safe" is the gate: speed never skips verify-live, diff review, git safety, or the
  cost recommendation. Fast AND safe — not fast INSTEAD of safe.

# ───────────────────────────────────────────────────────────
# SESSION START — load context automatically (free, read-only)
# ───────────────────────────────────────────────────────────
On every new chat, load empire context (no permission needed — these are free reads):
1. brain_status  (cheap pulse)
2. GET /context
3. GET /projects
4. GET /cards
5. GET /logs?limit=10
Header for all REST calls: x-brain-key: jim-brain-kje-2026-kingjames
Then confirm: "Jim Brain loaded. I can see [X] projects, [X] cards, and [X] memories.
Ready to build. What are we working on?"

# ───────────────────────────────────────────────────────────
# BRAIN — connection reference
# ───────────────────────────────────────────────────────────
Brain URL: https://jim-brain-production.up.railway.app   (current version: v1.9.0)
Key:       jim-brain-kje-2026-kingjames
MCP:       https://kje-mcp.onrender.com/mcp/T24NM1Sxbh7txJs-unNIjblaXMqA1OZW6gNU-Ud5Yjk/
VPS:       192.161.173.97 (Ubuntu 24.04)   |   Notify: POST /notify (channel: sms|email|both)
GitHub:    jharriGH   |   Local repos: C:\Users\Jim\Documents\GitHub\

Tools available: brain_status, brain_search, brain_get_project, brain_vault_search,
brain_log, brain_memory, run_build_task (METERED — Jim's go required).

Two logging endpoints:
- POST /log    → instant (<1s), audit only, NOT searchable. Automated/frequent events.
- POST /memory → semantic (60-90s), searchable. Decisions, milestones, lessons.

# ───────────────────────────────────────────────────────────
# TECH STACK (never suggest third-party alternatives like GHL/Zapier)
# ───────────────────────────────────────────────────────────
Frontend: Lovable | Backend: Python/FastAPI | DB: Supabase (PostgreSQL)
API hosting: Render | Workers/crons: Railway | Storage: Cloudflare R2 | CDN: Cloudflare Pages
AI: Claude API (claude-sonnet-4-6 default) | Memory: Jim Brain (mem0 + Qdrant)
Orchestration: n8n on Railway | Voice: Vapi.ai + AVA v6.4.0 | RVM: VoiceDropz
Email: ReachInbox + Instantly | LinkedIn: HeyReach | SMS: Twilio (866-621-7044 A2P)
Payments: Stripe

EMPIRE PRODUCTS: KJWidgetz | KJLE | Jim Brain | DemoBoosterz | DemoEnginez | VoiceDropz |
KJ SalesAgentz | UnhideLocal | SiteEnginez | ReviewBombz | KJ Autonomous |
KJ CodeDeck/BridgeDeck | IAMStillHere | AgentEnginez | TestEnginez | DaycareMarketerz |
FinanceIQ | IASY

# ───────────────────────────────────────────────────────────
# CODING RULES — ALWAYS
# ───────────────────────────────────────────────────────────
- Complete files only, no snippets or placeholders.
- Specify exact repo, Supabase project, service on every command.
- `git push origin main`  (NORMAL push — never --force; see §2).
- service_role key, never anon key.
- supabase.schema('name') not constructor chaining.
- .maybeSingle() not .single().
- await + try/catch on Supabase queries.
- Run curl from the RackNerd VPS, not Windows CMD.
- /log for fast logging; /memory for semantic decisions.
- PATCH /projects for project updates; PATCH /state for single metric updates.

# NEVER DO:
- Suggest GHL, Zapier, or stack alternatives.
- Use placeholders or PASTE_ID_HERE.
- Produce snippets — always complete files.
- Modify existing n8n workflows (new workflows only).
- Single quotes or em dashes in Brain content (use double quotes and hyphens).
- POST /state to update arrays (use the PATCH endpoints).

# ───────────────────────────────────────────────────────────
# SESSION END RULE
# ───────────────────────────────────────────────────────────
Every session ends with all three:
1. POST /memory — full session summary (BUILT / DECISIONS / BUGS FIXED / GOTCHAS / NEXT),
   tags ["[project]", "session_end"].
2. PATCH /projects — update next_action.
3. POST /cards — save updated BUILD_STATE card.
Confirm each succeeded, then give Jim a plain-English summary.

# GOTCHA LOGGING RULE:
Any bug, workaround, or lesson learned → log immediately via POST /memory (brain_memory),
tags ["[project]", "gotcha", "lesson"].

# ───────────────────────────────────────────────────────────
# BRAIN SYNC + ROADMAP (Brain-derived — do NOT hand-edit)
# ───────────────────────────────────────────────────────────
brain_sync.py runs daily at 7am, regenerating every repo's CLAUDE.md AND ROADMAP.md from Brain.
Manual run: python brain_sync.py  (location: C:\Users\Jim\Documents\GitHub\)
- The operating rules in this document live in the brain_sync CLAUDE.md template — edit them
  THERE, not per-repo.
- ROADMAP.md is RENDERED FROM BRAIN (each project's next_action + latest BUILD_STATE card +
  recent session summaries). Do NOT hand-edit per-repo ROADMAP.md — multiple writers are what
  caused the CLAUDE.md/ROADMAP.md merge conflicts we already hit. The roadmap updates itself
  because session-end already writes next_action + card + summary to Brain; brain_sync renders
  the file. One writer, no conflicts, always current.

# ───────────────────────────────────────────────────────────
# MANDATORY FOOTER — after every response
# ───────────────────────────────────────────────────────────
📊 [PROJECT] — [X]% complete | 📍 [PHASE] — [X]%
🔄 EMPIRE IN FLIGHT
| Session | Status | Jim Needed? |
(populate from brain_search("active session") or known active sessions)

# ───────────────────────────────────────────────────────────
# TEMPLATE — UNIVERSAL SESSION ENDER (paste to a CC to close out)
# ───────────────────────────────────────────────────────────
Session complete. Do all three now and confirm each:
1. POST /memory — SESSION SUMMARY [project]: BUILT / DECISIONS / BUGS FIXED / GOTCHAS / NEXT
   tags ["[project]", "session_end"]
2. PATCH /projects — next_action = [most important next task]  (match_by: id)
3. POST /cards — title "[PROJECT] BUILD_STATE [date]", project "[project]", content [markdown]
Then give a plain-English summary of what we accomplished.

---

## CURRENT STATUS
<!-- BRAIN-SYNC:START:STATUS -->
*Brain sync: June 22, 2026 07:36 PM PST*

<!-- BRAIN-SYNC:END:STATUS -->

---

## EMPIRE STATE & COSTS
<!-- BRAIN-SYNC:START:EMPIRE_STATE -->
- Clients: 0
- MRR: $0.00
- HOT leads: 0
- Last decision: None
<!-- BRAIN-SYNC:END:EMPIRE_STATE -->

---

## RECENT KJ_BRIDGEDECK MEMORIES
<!-- BRAIN-SYNC:START:MEMORIES -->
1. kj-bridgedeck should be RESET not pushed due to being a duplicate block, already onboarded on origin
2. Tags: project_created, kj_bridgedeck, infrastructure
3. Commit f2f14cf in kj-bridgedeck
4. URL is https://kjbridgedeck.com
5. kj-bridgedeck has two open PRs for Phase G schema
6. KJ_RULEZ Code Deployment Discipline rule committed and pushed to kj-bridgedeck
7. Tags: kj_bridgedeck, phase_g, cleanup_needed, pr_hygiene
8. BridgeDeck SC coordination on 2026-05-15
<!-- BRAIN-SYNC:END:MEMORIES -->

---

## BUILD STATE
<!-- BRAIN-SYNC:START:BUILD_STATE -->
*No build card in Brain yet.*
*brain_sync will auto-push BUILD_STATE.md if found in repo.*
*Or call brain_save_card() at end of next CC session.*
<!-- BRAIN-SYNC:END:BUILD_STATE -->

---

## MANUAL ADDITIONS
<!-- brain_sync.py never modifies below this line -->


---

## FIRST THING — DO THIS AUTOMATICALLY

```
brain_session_start(focus="[today's task]", product="kj_bridgedeck")
brain_search(query='kj_bridgedeck')
brain_list_cards()   # find build card
brain_get_card(id)   # load full spec
# THEN ask Jim what to tackle
```

**Do not wait to be asked. Always do this first.**

---

## SESSION END — DO THIS AUTOMATICALLY

```
brain_session_end(
  product="kj_bridgedeck",
  what_shipped="[what was built]",
  decisions="[key decisions]",
  next_action="[most important next task]"
)
brain_save_card(
  title="KJ_BRIDGEDECK BUILD_STATE [date]",
  project="kj_bridgedeck",
  content="[full build state md]"
)
```

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
- `CF_API_TOKEN`    (set 2026-05-07) — manages all Cloudflare zones + Pages projects
- `RAILWAY_TOKEN`   (pending — set when first Railway env op needed)

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

<!-- KJE-ONBOARD-V1 -->
## KJ Empire — SC Onboarding
This repo belongs to the KJ Empire (DevelopingRiches Inc, owner Jim Harris / jharriGH).
- Central repo: jharriGH/kjle. Brain: https://jim-brain-production.up.railway.app
- New SC seats: run brain_status, brain_search this repo's slug, and verify live state before declaring anything done.
- Decide-and-proceed. Cost-gate chargeable dispatches. Never echo secrets — pull keys from the Brain vault.
- See ROADMAP.md for status.
<!-- /KJE-ONBOARD-V1 -->
