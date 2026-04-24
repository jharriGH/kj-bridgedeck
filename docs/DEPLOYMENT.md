# Deployment Runbook

End-to-end steps to bring KJ BridgeDeck online from an empty Supabase + Render + Cloudflare + Jim's Windows machine.

Bridge-A produces the scaffold. Bridge-B/C/D/E fill in their pieces. This runbook glues them together.

---

## Prerequisites

- GitHub repo `jharriGH/kj-bridgedeck` exists + pushed (Bridge-A handles this).
- Supabase project `dhzpwobfihrprlcxqjbq` is live (already exists).
- Brain service `jim-brain-production` is live at `https://jim-brain-production.up.railway.app` (already exists).
- Windows 11 machine with PowerShell 7 (`pwsh`), Python 3.11+, WSL2 Ubuntu.
- Render.com account linked to the GitHub repo.
- Cloudflare account with Pages enabled.

---

## 1. Deploy the Supabase schema

> Required before Bridge-B/C can run.

1. Open Supabase dashboard → project `dhzpwobfihrprlcxqjbq` → SQL Editor.
2. Paste the entire contents of `supabase/schema.sql` into a new query.
3. Click **Run**.
4. Verify:
   ```sql
   SELECT count(*) FROM kjcodedeck.settings;
   -- expect: count >= 60
   SELECT table_name FROM information_schema.tables
     WHERE table_schema = 'kjcodedeck' ORDER BY table_name;
   -- expect: 11 tables listed
   ```
5. Grab the **service role key** from Settings → API → `service_role` secret. This goes in `.env` + Render env vars.

---

## 2. Wait for Bridge-B, C, D to complete

These run in parallel. Each will signal done in its own PowerShell session. Mark them off in `BUILD_STATE.md` as they land.

- Bridge-B produces `watcher/dist/bridgedeck-watcher.exe` + completes `install/install_watcher.ps1`.
- Bridge-C produces `api/main.py` + `api/requirements.txt` + all 40+ endpoints.
- Bridge-D produces `bridge-core/` modules + completes `install/install_piper.ps1`.

---

## 3. Deploy the API to Render

> After Bridge-C signals done.

1. In Render dashboard → **New** → **Blueprint** → pick the `jharriGH/kj-bridgedeck` repo.
2. Render detects `render.yaml` and creates the `kj-bridgedeck-api` web service.
3. In the service's **Environment** tab, fill in the secrets marked `sync: false`:
   - `SUPABASE_URL` (public URL from Supabase Settings → API)
   - `SUPABASE_SERVICE_KEY` (from step 1.5)
   - `SUPABASE_ANON_KEY`
   - `BRAIN_KEY` (`jim-brain-kje-2026-kingjames`)
   - `BRIDGEDECK_ADMIN_KEY` (`bridgedeck-kj-2026-kingjames` or rotate to a fresh UUID)
   - `ANTHROPIC_API_KEY`
   - `OPENAI_API_KEY`
4. Wait for the first deploy to finish. Tail logs until you see `Uvicorn running on 0.0.0.0:$PORT`.
5. Smoke-test:
   ```bash
   curl https://kj-bridgedeck-api.onrender.com/health
   # expect: {"healthy": true, "version": "...", "supabase": "ok", "brain": "ok"}
   ```
6. Note the public URL — this becomes `API_PUBLIC_URL` in the UI build.

---

## 4. Install the Watcher on Windows

> After Bridge-B signals done.

On Jim's Windows machine:

```pwsh
cd C:\Users\Jim\Documents\GitHub\kj-bridgedeck
git pull
cp .env.example .env
# edit .env with real keys
pwsh install/install_watcher.ps1
```

Verify:
```pwsh
Get-ScheduledTask -TaskName "BridgeDeck-Watcher"
Invoke-WebRequest http://localhost:7171/health | Select -Expand Content
# expect: {"healthy": true, "machine_id": "jim-windows-main", ...}
```

If the watcher can't bind to :7171, check for conflicts with `Get-NetTCPConnection -LocalPort 7171`.

---

## 5. Install Piper (local TTS)

> After Bridge-D signals done.

```pwsh
pwsh install/install_piper.ps1
```

The script downloads Piper + the `en_US-ryan-high` voice model into `bin/piper/`. It prints two paths — paste them into `.env`:

```
PIPER_BINARY_PATH=C:\Users\Jim\Documents\GitHub\kj-bridgedeck\bin\piper\piper.exe
PIPER_MODEL_PATH=C:\Users\Jim\Documents\GitHub\kj-bridgedeck\bin\piper\en_US-ryan-high.onnx
```

Smoke-test:
```pwsh
"The bridge is online" | & $env:PIPER_BINARY_PATH --model $env:PIPER_MODEL_PATH --output-raw | ffplay -f s16le -ar 22050 -i -
```

Also update the Supabase settings so the Bridge core reads the same values:
```sql
UPDATE kjcodedeck.settings
  SET value = '"C:\\Users\\Jim\\Documents\\GitHub\\kj-bridgedeck\\bin\\piper\\piper.exe"'
  WHERE namespace = 'voice' AND key = 'piper_binary_path';
UPDATE kjcodedeck.settings
  SET value = '"C:\\Users\\Jim\\Documents\\GitHub\\kj-bridgedeck\\bin\\piper\\en_US-ryan-high.onnx"'
  WHERE namespace = 'voice' AND key = 'piper_model_path';
```

Then hit `POST https://kj-bridgedeck-api.onrender.com/admin/reload-settings` (with admin key).

---

## 6. Schedule the Brain flush task

> One-time Windows setup, any time after step 4.

Run as Jim (not elevated):

```pwsh
$action = New-ScheduledTaskAction `
    -Execute "pwsh" `
    -Argument "-NoProfile -File C:\Users\Jim\Documents\GitHub\kj-bridgedeck\install\brain_flush.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "BridgeDeck-BrainFlush" `
    -Action $action -Trigger $trigger -RunLevel Limited
```

Confirm it fires:
```pwsh
Start-ScheduledTask -TaskName "BridgeDeck-BrainFlush"
Get-Content "$env:TEMP\bridgedeck_flush.log" -Tail 5
```

---

## 7. Deploy the UI to Cloudflare Pages

> After Bridge-E signals done.

1. In Cloudflare dashboard → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**.
2. Pick `jharriGH/kj-bridgedeck`. Production branch: `main`.
3. Build settings:
   - Build command: `cd bridge-ui && npm install && npm run build`
   - Build output: `bridge-ui/dist`
   - Root directory: `/`
4. Environment variables (Production):
   - `VITE_API_URL` = the Render public URL from step 3.6
   - `VITE_ADMIN_KEY` = `BRIDGEDECK_ADMIN_KEY` value
5. Deploy. First build takes ~2 min.
6. Note the `*.pages.dev` URL. Optional: attach a custom domain (`bridgedeck.developingriches.com`).

---

## 8. Configure the Brain project

> Tell Brain about BridgeDeck so the UI can read its review queue, cards, etc.

In the Brain admin UI (or via `POST /brain/projects`):

```json
{
  "slug": "kj-bridgedeck",
  "display_name": "KJ BridgeDeck",
  "emoji": "🖥️",
  "color": "#00E5FF",
  "repo_url": "https://github.com/jharriGH/kj-bridgedeck",
  "description": "Visual terminal management + voice-first empire command interface"
}
```

---

## 9. Six end-to-end test scenarios

Run each scenario with the UI open at `https://bridgedeck.pages.dev`.

### 9.1 Session visibility
1. Open a new Windows Terminal, run `claude` under any project.
2. Within 3 seconds, the project tile appears on the Monitor tab with status `processing`.
3. Ask Claude a question. Tile status flips to `waiting` as response streams.

### 9.2 Session end → handoff
1. Exit the Claude session (`/exit`).
2. Tile shows `ended`. Within 30 seconds:
   - `kjcodedeck.session_archive` has a row for the session.
   - `kjcodedeck.session_handoffs` has a row with `brain_sync='sent'`.
   - Brain's review queue shows the handoff if confidence < 0.85.

### 9.3 Auto-approve rule
1. Create a rule: project `chef-os`, allow, regex `^Continue\?`, max 5/hr.
2. Start a chef-os session, trigger an approval prompt.
3. Watcher sends `1\n` automatically; history shows `auto_approve.fired`.

### 9.4 Bridge chat — status query
1. Click the Bridge tab, type "status".
2. Response streams within 2s, lists all active sessions with costs.
3. `bridge_turns` has a new row.

### 9.5 Bridge chat — action queue
1. Voice prompt: "launch chef-os and ask it to resume the recipe importer".
2. Whisper transcribes, Bridge responds, confirm action.
3. `action_queue` gets a `launch_session` row.
4. Watcher spawns a new Windows Terminal with `claude` in the chef-os directory.
5. The initial prompt is typed for you.

### 9.6 Budget cap
1. Set `empire_daily_cap_usd` to something near current spend.
2. Run a session that pushes total over 80%.
3. `budget.warn_threshold_hit` appears in history; UI shows a banner; notification fires (if configured).

---

## 10. Operational daily checklist

- Monitor the **Admin → Review Queue** tab for low-confidence handoffs; accept/reject each.
- Check the **Admin → Budget** panel — any project nearing cap?
- Verify `$env:TEMP\bridgedeck_flush.log` has entries in the last hour.
- `SELECT count(*) FROM kjcodedeck.history_log WHERE event_category='error' AND created_at > now() - interval '24 hours'` — review any errors.
