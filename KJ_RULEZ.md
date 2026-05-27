# KJ RULEZ â€” Standing Rules for All KJE Builds

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
   - Field name mappings to local schema (e.g. `brain.id â†’ local.slug`)
   - Pseudo-projects to filter (e.g. `{"id":"all"}` is a UI placeholder)

4. **WHAT COUNTS AS VERIFYING:**

   - Real curl output showing HTTP 200 + JSON body
   - Documented field mapping table
   - Explicit handling of pseudo/special rows

5. **WHAT DOES NOT COUNT:**

   - "It probably looks like..."
   - Assuming endpoint paths from convention (e.g. `/codedeck/X` when `/X` is
     real)
   - Reusing endpoints from prior product memory without re-verifying â€” Brain
     versions evolve

### Endpoint catalog (verified live 2026-04-27)

See `CLAUDE.md` in `kj-bridgedeck` for the full GET/POST/PATCH/DELETE
catalog. Until a project moves it elsewhere, treat that catalog as the
empire-wide canonical list and update it when Brain changes.

---

## EMPIRE COST LOGGING RULE

Any KJE product that calls Anthropic, OpenAI, or any LLM API MUST
instrument cost reporting via the `kje-cost-logger` module per
`docs/EMPIRE_COST_LOGGING_BUILD_CARD.md`.

This is the empire-wide standard for cost visibility. Without
instrumentation, a product is not considered production-ready.

### Default integration

```bash
pip install kje-cost-logger
```

```python
from kje_cost_logger import CostLogger
import os

logger = CostLogger(
    bridgedeck_url=os.environ["BRIDGEDECK_URL"],
    api_key=os.environ["BRIDGEDECK_INGEST_KEY"],
    source_system="<your_product_name>",     # must match a slug in
                                              # api/routes/cost.py::EXPECTED_PRODUCTS
    project_slug="<brain_project_slug>",
)

# After every Anthropic call:
await logger.log_anthropic_call(response, model="...", intent="...")
```

### Why self-reporting (not provider Admin APIs)

Anthropic Admin API ingestion is the gold standard for reconciliation
but it's gated behind Build Tier 2+ / Enterprise. Live verification
2026-04-28 confirmed the regular `sk-ant-api03-...` messages key returns
HTTP 401 "invalid x-api-key" against `/v1/organizations/usage_report/messages`
and `/cost_report` â€” admin-only. Until the empire qualifies for that
tier, self-reporting via BridgeDeck `/cost/ingest` is the baseline
standard.

### Coverage check

The BridgeDeck Cost tab includes a Coverage Report listing every product
in `EXPECTED_PRODUCTS` and whether it posted to `/cost/ingest` in the
last 24h. Products marked `instrumented: false` are the audit list.

---

## ENV VAR AUTOMATION RULE (added 2026-04-29)

Jim never manually updates env vars or secrets on any deployment platform. CC always handles env var operations programmatically.

### Required CC behavior

When env var changes are needed, CC MUST:

1. Use the platform's API/CLI to set vars directly:
   - Render: Render API v1 â€” POST /v1/services/{service_id}/env-vars
   - Railway: railway CLI or GraphQL API
   - Cloudflare Pages: wrangler pages secret put
   - Vercel: vercel env add
   - GitHub Actions: gh secret set

2. Trigger a redeploy if the platform doesn't auto-redeploy on env change.

3. Verify the new var landed by curl-checking the deployed service health endpoint or env reflection (where available).

4. Report exactly what was set, where, and the deployment status â€” no placeholder text like "you should add X to Y."

### Required environment for CC

For automation to work, these must be in CC's environment (per service it manages):
- RENDER_API_KEY (account-scoped, manages all Render services)
- RAILWAY_TOKEN (project-scoped per Railway project)
- CF_API_TOKEN (Cloudflare account-scoped)

If any of these is missing when CC needs to update env vars, CC must STOP and ask Jim to add the credential ONCE â€” never ask Jim to manually add env vars to a platform.

### Exceptions

The only acceptable manual env var asks are:

1. First-time API key generation when the credential doesn't yet exist anywhere (e.g. "generate a new Anthropic key, paste it back to me â€” then I'll handle distributing it to all services").

2. Browser OAuth flows that physically require Jim to click Allow on a consent screen (e.g. first-time gh auth login).

Everything else: CC automates.

### Why this rule exists

Jim has arthritis and brain fog. Manual dashboard clicking across 5+ services to set the same 2 env vars is painful and error-prone. CC has the credentials and APIs to do it instantly. CC never asks Jim to do this manual work going forward.

---

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
MANDATORY BRAIN SESSION START RULE
Added: 2026-05-05
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

EVERY Claude session â€” claude.ai, Claude Code,
or desktop app â€” MUST start with Brain context.
No exceptions. No excuses.

WHAT IS BRAIN?
Jim Brain is the persistent memory and 
intelligence layer for the entire King James 
Empire. It stores every decision, every build 
state, every project status, and every lesson 
learned across all products.
URL: https://jim-brain-production.up.railway.app
Key: jim-brain-kje-2026-kingjames

FOR CLAUDE CODE SESSIONS:
First thing typed in every CC session:
brain_session_start(
  focus="[what you are building today]",
  product="[project_id]"
)
This loads full empire context, recent memories,
and the latest build card automatically.
Available project IDs: kjwidgetz, kjle, 
jim_brain, demoboosterz, demoenginez,
kj_salesagentz, kj_autonomous, voicedropz,
unhidelocal, siteenginez, reviewbombz,
iasy, kj_codedeck, agentenginez

FOR CLAUDE.AI SESSIONS:
Open Brain UI â†’ select project in filter bar
â†’ click Copy Session Starter (top right)
â†’ paste as FIRST message in new chat

FOR QUICK SESSIONS (no Brain UI available):
Paste this as first message:
---
I am Jim Harris, King James Empire.
Brain: https://jim-brain-production.up.railway.app
Key: jim-brain-kje-2026-kingjames
Project: [project name]
Please fetch GET /context GET /projects GET /cards
and give me a full briefing before we start.
---

IF A CLAUDE ASKS "WHAT IS BRAIN?" OR SEEMS
UNINFORMED ABOUT THE EMPIRE:
STOP immediately. Do not continue building.
Paste the session starter above first.
A Claude without Brain context will waste time
and make decisions that contradict empire rules.

BRAIN SESSION END RULE:
Every CC session MUST end with:
brain_session_end(
  product="[project_id]",
  what_shipped="[what was built]",
  decisions="[key decisions made]",
  next_action="[single most important next task]"
)
Then: brain_save_card(title, project, content)
with the full current build state.

BRAIN SYNC RULE:
Run every morning before starting work:
python C:\Users\Jim\Documents\GitHub\brain_sync.py
This refreshes all CLAUDE.md files across all
repos with the latest Brain state.
Automated via Windows Task Scheduler at 7am.

GOTCHA LOGGING RULE:
Any bug, workaround, or lesson learned MUST
be logged to Brain immediately:
brain_memory(
  content="[project] gotcha: [what happened]
  and [how to avoid next time]",
  tags=["[project]", "gotcha", "lesson"]
)
Do not wait until end of session.
Log gotchas while context is fresh.

NEW PROJECT RULE:
Every new KJE project must be registered in
Brain before building starts:
1. Brain UI â†’ Manage Projects â†’ Add New
2. Fill: name, emoji, status, description,
   repo_path
3. python brain_sync.py [project_id]
4. Start building with brain_session_start()

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
BRAIN LOGGING OWNERSHIP RULE
Added: 2026-05-05
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

BRAIN LOGGING IS NOT OPTIONAL AND NOT JIM'S JOB.
Claude logs to Brain. Not Jim. Ever.

If you are asking Jim which option to use for
logging â€” you are doing it wrong. Pick one and execute.

RULES FOR EVERY CLAUDE SESSION:
1. YOU decide how to log. Never ask Jim.
2. YOU write the curl commands. Never ask Jim.
3. YOU execute the logging. Never ask Jim.
4. YOU choose /log or /memory based on these rules:
   - Decision/lesson/bug fix â†’ POST /memory (semantic)
   - Progress/event/automated â†’ POST /log (fast)
5. YOU update next_action on the project.
6. YOU save the build card at session end.

WHEN ASKED "WHAT OPTION?" OR "HOW SHOULD I LOG?":
Wrong question. There is no option. Just log it.
Use Option B always â€” write the script, run it,
confirm it worked, report back to Jim with results.

CLOSING RITUAL â€” MANDATORY EVERY SESSION:
Step 1: POST /memory â€” full session summary
Step 2: PATCH /projects â€” update next_action
Step 3: POST /cards â€” save full build state
No exceptions. No asking. Just execute.

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
STATUS BANNER + CHAT SIZE + EMPIRE AWARENESS RULE
Added: 2026-05-10
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

EVERY response from EVERY Claude (SC or CC) MUST
end with this banner â€” no exceptions.

â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ ðŸ“Š PROJECT: [name] â€” [X]% complete         â”‚
â”‚ ðŸ“ PHASE:   [current phase] â€” [X]% complete â”‚
â”‚ ðŸ’¬ CHAT:    ~[X]% full                     â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜

For SC sessions, also include the active sessions
table populated from brain_search("active session"):

â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ Session      â”‚ Status                â”‚ Jim Needed?  â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚ [project] SC â”‚ [what it's doing]     â”‚ [Yes/No]     â”‚
â”‚ [project] CC â”‚ [building X]          â”‚ Noneâ€”auto    â”‚
â”‚ This chat    â”‚ Strategic coordinator â”‚ Reading this â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜

CHAT SIZE ESTIMATION:
- Rough formula: message_count Ã— 1500 / 200000 Ã— 100
- Warn at 70%: "ðŸ’¬ Chat getting full â€” consider new chat"
- Hard suggest at 85%: "âš ï¸ Open new chat now to avoid losing context"
- Critical at 95%: "ðŸš¨ OPEN NEW CHAT IMMEDIATELY"

FULL BRAIN + MCP + VAULT + DISPATCHER AWARENESS
(every Claude must know without being told):

  BRAIN API:  https://jim-brain-production.up.railway.app
  BRAIN KEY:  jim-brain-kje-2026-kingjames  (header: x-brain-key)
  MCP URL:    https://kje-mcp.onrender.com/mcp/T24NM1Sxbh7txJs-unNIjblaXMqA1OZW6gNU-Ud5Yjk/
  VPS:        192.161.173.97 (ccrunner, /usr/local/bin/claude)
  DISPATCHER: http://192.161.173.97:8091/dispatch
  NOTIFY:     POST /notify  body {severity, message, channel, project}

7 BRAIN TOOLS (use without being asked):
  brain_status        â€” empire health check
  brain_search        â€” search all memories
  brain_get_project   â€” full project context
  brain_vault_search  â€” ANY credential from vault
  brain_log           â€” fast event log
  brain_memory        â€” semantic memory store
  run_build_task      â€” dispatch CC on VPS

VAULT HAS EVERYTHING â€” never ask Jim for:
  API keys, tokens, passwords, Supabase URLs,
  Stripe keys, Twilio creds, Render API keys,
  Railway tokens, GitHub PAT, RackNerd VPS creds,
  Resend keys, Anthropic keys, Cloudflare tokens,
  Qdrant, n8n, Vapi â€” everything is in vault.
  Always: brain_vault_search("what you need")

No response is complete without the banner.
No exception. No excuse.

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
AUTONOMOUS EXECUTION RULE
Added: 2026-05-07
â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

EVERY Claude â€” SC or CC â€” operates autonomously.
Jim is NEVER the middle man. Ever.

WHEN GIVEN A TASK:
1. brain_get_project() â†’ load full context
2. brain_vault_search() â†’ get any credential
3. run_build_task() â†’ dispatch CC on VPS
4. brain_search() â†’ monitor for completion
5. Report to Jim ONLY when done or truly blocked

NEVER:
- Ask Jim for credentials
- Ask Jim to copy/paste between windows
- Ask Jim which option to choose
- Ask Jim to run any command
- Ask Jim to be the middle man between SC and CC
- Present options and wait â€” pick one and execute

ALWAYS:
- Get everything from Brain vault
- Dispatch CC via run_build_task
- Log all decisions to Brain
- Work autonomously until complete
- Interrupt Jim ONLY for:
  * Business decisions requiring his judgment
  * New credentials not in vault
  * Task complete â€” here are results

VPS DISPATCHER:
URL: http://192.161.173.97:8091/dispatch
Key: stored in vault under empire/VPS_DISPATCH_KEY
Claude Code: /usr/local/bin/claude on VPS

KJE MCP SERVER:
URL: stored in vault under empire/KJE_MCP_URL
Tools: brain_status, brain_search,
       brain_get_project, brain_vault_search,
       brain_log, brain_memory, run_build_task

â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

---

## REVISION LOG

- **2026-04-27**: Brain Endpoint Verification rule introduced after
  BridgeDeck Bridge-C burned ~2 hours debugging `/codedeck/projects`
  (didn't exist) + `Authorization: Bearer` (wrong header). Real endpoint
  was `/projects` with `x-brain-key` header. Both were guessable from
  convention but neither was verified against live Brain.
- **2026-04-29**: Empire Cost Logging rule introduced. Anthropic Admin
  API ingestion (Phase 3.1) blocked behind Build Tier 2+ â€” pivoted to
  empire-wide self-reporting via `kje-cost-logger` module + BridgeDeck
  `/cost/ingest` endpoint.
- **2026-04-29**: Env Var Automation rule introduced. Jim never updates
  platform env vars manually â€” CC handles all secret distribution via
  Render/Railway/Cloudflare/Vercel/GitHub APIs. Required tokens
  (RENDER_API_KEY, RAILWAY_TOKEN, CF_API_TOKEN) gated through CC's
  environment; CC asks once if missing, never repeatedly.
- **2026-05-05**: Brain Logging Ownership rule introduced. Brain logging
  is Claude's job â€” not Jim's. CC must pick /log vs /memory itself,
  write and execute the curl, then run the closing ritual (POST /memory,
  PATCH /projects, POST /cards) at session end. No more asking Jim
  "which option?" â€” there is no option, just log it.
- **2026-05-07**: Autonomous Execution rule introduced. SC and CC work
  together via run_build_task on the VPS dispatcher; Jim is never the
  middle man between them. All credentials come from the Brain vault.
  No options-and-wait, no copy/paste between windows, no asking which
  command to run. Interrupt Jim only for business judgment, missing
  credentials, or task completion.
- **2026-05-10**: Status Banner + Chat Size + Empire Awareness rule
  introduced. Every Claude (SC or CC) must end every response with a
  status banner (project %, phase %, chat %), and SCs must show an
  active sessions table. Chat-size warnings fire at 70/85/95%. Full
  Brain/MCP/Vault/Dispatcher coordinates are now baked into the rule
  so every Claude knows them without being told. AUTONOMOUS_EXECUTION_BLOCK
  in brain_sync.py updated in lockstep so all repos pick up the rule
  on next sync.

---

## Code Deployment Discipline

### Code Deployment Discipline
- **Never retest a write-gate against unmerged code on production.** If a PR introduces a gate (auth check, kill switch, suppression flag, etc.), do NOT POST to the gated production endpoint from a CC session until the PR is merged. The gate does not exist in production yet, so the request runs against pre-gate code and can fire the very destructive operation the gate was meant to prevent.
- Two approved retest paths:
  1. Test against a Railway preview environment built from the PR branch
  2. Wait until merge + deploy completes, then verify against production
- Cost of violating this rule: the 2026-05-27 scale_trigger incident, ~$30 real spend plus 2,349 polluted Supabase rows. Source: Brain memory rbz-scale-trigger-caller-forensics_bcaeffd4.
- This rule applies to BOTH human-initiated and CC-dispatched retests.
