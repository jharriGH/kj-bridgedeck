# Post-Deploy Manual Steps

Path A handed off code-complete on **2026-04-26**. The pieces below need a
human at a dashboard or with admin elevation. Each step is independent; pick
any order.

---

## 0. Fill in `.env` placeholders (30 seconds)

Open `.env` in the repo root. Replace every `__JIM_PASTE__` with the real
value:

```
SUPABASE_SERVICE_KEY=<Supabase → Project Settings → API → service_role>
SUPABASE_ANON_KEY=<Supabase → Project Settings → API → anon public>
ANTHROPIC_API_KEY=<console.anthropic.com → API Keys>
OPENAI_API_KEY=<platform.openai.com → API Keys>
```

These mirror what Render needs (step 2 below). After saving, the watcher and
local API can run; nothing in cloud needs them.

---

## 1. Deploy the Supabase schema (one-time)

> Required before anything writes to Supabase.

1. Open Supabase → project `dhzpwobfihrprlcxqjbq` → **SQL Editor**.
2. New query → paste the entire contents of `supabase/schema.sql`.
3. Run.
4. Verify:
   ```sql
   SELECT count(*) FROM kjcodedeck.settings;
   -- expect: count >= 60
   SELECT table_name FROM information_schema.tables
     WHERE table_schema = 'kjcodedeck' ORDER BY table_name;
   -- expect: 11 tables
   ```

---

## 2. Render — deploy the API

The current Render hostname `kj-bridgedeck-api.onrender.com` returns
`x-render-routing: no-server` — i.e. the service does not exist. Create it:

1. **Render dashboard → New → Blueprint**.
2. Connect the GitHub repo `jharriGH/kj-bridgedeck`. Render reads
   `render.yaml` and proposes the `kj-bridgedeck-api` web service (Oregon,
   Starter plan, Python 3.11.9, build `pip install -r api/requirements.txt`,
   start `cd api && uvicorn main:app --host 0.0.0.0 --port $PORT`).
3. Click **Apply** to create.
4. **Environment** tab → fill the secrets marked `sync: false` in
   `render.yaml`. Use the same values as `.env`:
   - `SUPABASE_URL=https://dhzpwobfihrprlcxqjbq.supabase.co`
   - `SUPABASE_SERVICE_KEY` (service_role key)
   - `SUPABASE_ANON_KEY` (anon key)
   - `BRAIN_API_URL=https://jim-brain-production.up.railway.app`
   - `BRAIN_KEY=jim-brain-kje-2026-kingjames`
   - `BRIDGEDECK_ADMIN_KEY=bridgedeck-kj-2026-kingjames`
   - `ANTHROPIC_API_KEY=...`
   - `OPENAI_API_KEY=...`
   - Leave `WATCHER_HOST` set to `http://localhost:7171` (cloud cannot reach
     it — the API will return 503 with a friendly message on session-control
     routes; that's expected until you run a local companion API).
5. Wait for the first deploy. Tail logs until you see
   `Uvicorn running on 0.0.0.0:$PORT`.
6. Smoke-test:
   ```bash
   curl https://kj-bridgedeck-api.onrender.com/health
   # expect: {"healthy": true, "version": "0.1.0", "supabase": "ok",
   #          "brain": "ok", "watcher": "down" or "not_configured", ...}

   curl -H "Authorization: Bearer bridgedeck-kj-2026-kingjames" \
        https://kj-bridgedeck-api.onrender.com/projects
   ```
7. Open `https://kj-bridgedeck-api.onrender.com/docs` — Swagger should list
   ~57 routes.

If you see `ImportError: bridge_core` in logs, confirm Render ran the
editable install line at the bottom of `api/requirements.txt`
(`-e ./bridge-core`). The build runs from the repo root, so the relative path
resolves correctly.

---

## 3. Cloudflare Pages — deploy the UI

Two options; pick one.

### Option A — Wrangler from your machine (one command)

```bash
cd bridge-ui
# First time only:
npx --yes wrangler@4 login
# Every deploy:
API_URL=https://kj-bridgedeck-api.onrender.com node scripts/build.mjs
npx --yes wrangler@4 pages deploy dist --project-name=kj-bridgedeck-ui --branch=main
```

The first run will create the project. The output URL is
`https://kj-bridgedeck-ui.pages.dev`.

### Option B — Cloudflare dashboard (auto-deploy on push)

1. **Cloudflare dashboard → Workers & Pages → Create → Pages → Connect to Git**.
2. Repo: `jharriGH/kj-bridgedeck`. Production branch: `main`.
3. Build settings:
   - Framework preset: **None**
   - Build command: `cd bridge-ui && node scripts/build.mjs`
   - Build output directory: `bridge-ui/dist`
   - Root directory: `/`
4. Environment variables (Production):
   - `API_URL` = `https://kj-bridgedeck-api.onrender.com`
   - `UI_VERSION` = `1.0.0`
5. Deploy. First build is ~30s.

After deploy, open the `*.pages.dev` URL. The UI prompts for the admin key
on first load — paste `bridgedeck-kj-2026-kingjames` and save (stored in
localStorage; never leaves your browser except as the `Authorization` header).

### Optional — custom domain

Cloudflare Pages → `kj-bridgedeck-ui` → **Custom domains** → Add
`bridge.kjempire.com` (or whatever subdomain you want). DNS auto-configures
if the parent domain is on Cloudflare.

---

## 4. Update Supabase Piper paths (deferred SQL)

Path A could not write to Supabase (no anon/service key was available
during automation). Run this in Supabase SQL Editor after step 1 + Piper
install (step 5 below or already done):

```sql
UPDATE kjcodedeck.settings
   SET value = '"C:\\Users\\Jim\\Documents\\GitHub\\kj-bridgedeck\\bin\\piper\\piper\\piper.exe"'
 WHERE namespace = 'voice' AND key = 'piper_binary_path';

UPDATE kjcodedeck.settings
   SET value = '"C:\\Users\\Jim\\Documents\\GitHub\\kj-bridgedeck\\bin\\piper\\voices\\en_US-ryan-high.onnx"'
 WHERE namespace = 'voice' AND key = 'piper_model_path';
```

Then `POST /settings/reset` to clear the cache:

```bash
curl -X POST -H "Authorization: Bearer bridgedeck-kj-2026-kingjames" \
  https://kj-bridgedeck-api.onrender.com/settings/reset
```

Note: Path A already wrote both paths into local `.env`, so the watcher and
any locally-run API will pick them up automatically.

---

## 5. Install Watcher as a Windows Scheduled Task (admin elevation)

The watcher .exe was built by Path A
(`watcher/dist/kj-bridgedeck-watcher.exe`, 47.6 MB). Registering it as a
Windows Scheduled Task (so it runs on logon) requires an elevated PowerShell
prompt. Open PowerShell as Administrator and:

```pwsh
cd C:\Users\Jim\Documents\GitHub\kj-bridgedeck
.\install\install_watcher.ps1
```

Verify:

```pwsh
Get-ScheduledTask -TaskName "BridgeDeck-Watcher"
Invoke-WebRequest http://localhost:7171/health | Select -Expand Content
# expect: {"healthy": true, "machine_id": "jim-windows-main", ...}
```

If `:7171` fails to bind, check `Get-NetTCPConnection -LocalPort 7171` and
kill the offender.

---

## 6. Schedule the Brain flush (no admin needed)

```pwsh
$action = New-ScheduledTaskAction `
    -Execute "powershell" `
    -Argument "-NoProfile -File C:\Users\Jim\Documents\GitHub\kj-bridgedeck\install\brain_flush.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "BridgeDeck-BrainFlush" `
    -Action $action -Trigger $trigger -RunLevel Limited
```

Confirm:

```pwsh
Start-ScheduledTask -TaskName "BridgeDeck-BrainFlush"
Get-Content "$env:TEMP\bridgedeck_flush.log" -Tail 5
```

---

## 7. Final smoke tests (paste-ready)

After steps 1–3, run:

```bash
KEY="bridgedeck-kj-2026-kingjames"
API="https://kj-bridgedeck-api.onrender.com"

# 1. Health
curl -s "$API/health" | jq

# 2. Auth-required route
curl -s -H "Authorization: Bearer $KEY" "$API/projects" | jq '.projects | length'

# 3. Settings cache populated?
curl -s -H "Authorization: Bearer $KEY" "$API/settings/voice" | jq

# 4. Bridge chat (status query — Haiku route)
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"message":"status","stream":true}' "$API/bridge/chat" | head -40

# 5. Action queue read
curl -s -H "Authorization: Bearer $KEY" "$API/actions" | jq '.actions | length'

# 6. UI reachable
curl -s -o /dev/null -w 'UI HTTP %{http_code}\n' https://kj-bridgedeck-ui.pages.dev
```

For the six end-to-end UX scenarios (session visibility, handoff, auto-approve,
voice round-trip, action queue, budget cap), follow `docs/DEPLOYMENT.md` §9.

---

## 8. Known drift / footnotes

- **Brain version.** `CLAUDE.md` documents Brain v1.4.0 but the live
  service at `https://jim-brain-production.up.railway.app/health` reports
  v1.3.2 as of the Path A run on 2026-04-26. The handoff payload contract
  in `shared/contracts.py` is annotated "matches Brain v1.4.0 exactly" —
  test handoffs early to confirm the v1.3.2 endpoint accepts that schema.
  If Brain rejects, downgrade `SessionHandoff` or upgrade Brain.
- **Bridge-D voice service.** Whisper requires `OPENAI_API_KEY`; Piper
  synthesis requires `PIPER_BINARY_PATH` + `PIPER_MODEL_PATH` on the host
  running the API. Render has neither, so `/bridge/voice/synthesize` will
  503 in cloud mode — the UI auto-falls-back to the browser's built-in
  Web Speech TTS in that case (you'll hear it, just not in Ryan's voice).
- **bridge_core schema-qualified table names.** `bridge_core.chat` and
  `bridge_core.actions` use string constants like
  `"kjcodedeck.bridge_conversations"`. supabase-py's `.table()` doesn't
  accept schema-qualified names natively, so `api/main.py` wraps the
  client in a `_SchemaQualifiedSupabase` shim that splits on `.` and
  forwards to `client.postgrest.schema(s).from_(t)`. If you ever switch
  bridge_core's table names to bare ones, drop the shim.
- **Render cold start.** Starter plan idles after 15min. First request after
  idle takes ~20s. The UI polls `/sessions/live` every 3s once you're
  in Monitor, so you'll only see the cold-start lag once per session.

---

## 9. Quick reference

| Service | URL | Auth |
|---|---|---|
| UI | https://kj-bridgedeck-ui.pages.dev | none (browser holds admin key) |
| API | https://kj-bridgedeck-api.onrender.com | `Authorization: Bearer $KEY` |
| Brain | https://jim-brain-production.up.railway.app | `x-brain-key` header |
| Supabase | https://dhzpwobfihrprlcxqjbq.supabase.co | `apikey` header |
| Watcher (local) | http://localhost:7171 | `X-BridgeDeck-Admin-Key` header |

| Local artifact | Path | Status |
|---|---|---|
| Watcher .exe | `watcher/dist/kj-bridgedeck-watcher.exe` | Built (47.6 MB) |
| Piper binary | `bin/piper/piper/piper.exe` | Installed (510 KB) |
| Piper voice | `bin/piper/voices/en_US-ryan-high.onnx` | Installed |
| `.env` | `.env` | Created — fill 4 placeholders |
