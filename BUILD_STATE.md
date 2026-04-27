# KJ BridgeDeck — Build State

## Version: 1.0.0-rc1 (code complete, awaiting cloud deploy)

## Parallel build status

- [x] **Bridge-A** (Foundation): Schema, contracts, repo bootstrap — 2026-04-23
- [x] **Bridge-B** (Watcher): Python watcher on Windows — 2026-04-23 (.exe built 2026-04-26)
- [x] **Bridge-C** (API): FastAPI service on Render — 2026-04-23
- [x] **Bridge-D** (Bridge Core): Chat, voice, action executor — 2026-04-23
- [x] **Bridge-E** (UI): Standalone HTML + Cloudflare Pages — 2026-04-26
- [x] **Path A integration pass** — bridge.py wired, ActionExecutor in
  lifespan, schema shim, .env scaffolded, watcher .exe built, Piper
  installed, UI authored — 2026-04-26

## Build artifacts (local)

- `watcher/dist/kj-bridgedeck-watcher.exe` — 47.6 MB ✓
- `bin/piper/piper/piper.exe` — 510 KB ✓
- `bin/piper/voices/en_US-ryan-high.onnx` ✓
- `bridge-ui/dist/` — static UI (index.html + 8 JS modules + 1 CSS) ✓
- `.env` — 4 placeholders awaiting paste

## Foundation deliverables (Bridge-A, complete)

- [x] `supabase/schema.sql` — 11 tables, indexes, RLS, ~60 seed settings rows
- [x] `shared/contracts.py` — Pydantic models for every cross-agent shape
- [x] `shared/contracts.ts` — TypeScript mirrors
- [x] `render.yaml` — API deployment config
- [x] `install/brain_flush.ps1` — memory queue flush for Task Scheduler
- [x] `install/install_watcher.ps1` — needs admin to register Scheduled Task
- [x] `install/install_piper.ps1` — ran clean (PS 5.1) on 2026-04-26
- [x] `docs/ADMIN_SETTINGS.md`
- [x] `docs/HISTORY_LOG.md`
- [x] `docs/DEPLOYMENT.md`
- [x] `docs/POST_DEPLOY.md` — manual steps remaining (NEW)
- [x] `docs/HANDOFFS/`
- [x] `BRIDGEDECK_SPEC.md`
- [x] `CLAUDE.md`
- [x] `.env.example`
- [x] `.gitignore` (with `bridge-ui/dist/` carve-out)

## Live-system status (real, as of 2026-04-26)

| Component | URL | Status |
|---|---|---|
| Brain | https://jim-brain-production.up.railway.app | ✅ HTTP 200 (v1.3.2) |
| Render API | https://kj-bridgedeck-api.onrender.com | ❌ HTTP 404 — service not yet created |
| Supabase | https://dhzpwobfihrprlcxqjbq.supabase.co | 🟡 401 (reachable; needs schema deploy + key) |
| Cloudflare Pages UI | https://kj-bridgedeck-ui.pages.dev | ⏳ not yet deployed |
| Watcher local API | http://localhost:7171 | ⏳ exe built; needs admin to register Scheduled Task |

## Manual steps remaining

See `docs/POST_DEPLOY.md`. Summary:

1. Fill 4 `__JIM_PASTE__` values in `.env`.
2. Deploy `supabase/schema.sql` in Supabase SQL Editor.
3. Create Render Blueprint from `render.yaml` + paste the same secrets in
   the dashboard.
4. Cloudflare Pages: `npm run deploy` from `bridge-ui/` (or git auto-deploy).
5. Update Supabase `voice.piper_*` settings (deferred SQL in POST_DEPLOY.md).
6. Admin PowerShell: `.\install\install_watcher.ps1` to register the
   watcher Scheduled Task.
7. Schedule `brain_flush.ps1` (no admin needed).
8. Run the 6 end-to-end smoke scenarios from `docs/DEPLOYMENT.md` §9.

## Known drift / footnotes

- **Brain v1.3.2 vs v1.4.0.** `CLAUDE.md` and `shared/contracts.py` annotate
  v1.4.0; live Brain reports v1.3.2. Test the handoff schema early.
- **Render cold start.** Starter plan idles after 15min — first hit is ~20s.
- **Voice TTS.** Render can't run Piper (no binary in container). The UI
  falls back to Web Speech API automatically when Piper returns 503.

## Integration verification checklist (post-cloud-deploy)

- [ ] `GET /health` returns supabase=ok, brain=ok
- [ ] Watcher writes to `kjcodedeck.live_sessions` every 3 sec
- [ ] API reads live sessions and proxies session control to localhost:7171
- [ ] Bridge `/chat` SSE stream returns intent/sources/deltas/done events
- [ ] Voice `/transcribe` round-trips a recorded blob through Whisper
- [ ] Voice `/synthesize` returns WAV from Piper (or 503 → Web Speech fallback)
- [ ] Session end → Haiku summary → Brain handoff → row in `session_handoffs`
- [ ] Low-confidence handoff (<0.85) appears in Brain review queue
- [ ] Action queue: `launch_session` directive from Bridge → watcher spawns terminal

## Known constraints (unchanged)

- **Windows-first.** WSL2 Ubuntu available; installer targets Windows native.
- **Brain v1.x is source of truth** for memory, context, and review queue.
- **No `watchdog`** — poll Claude Code process list every 3 sec.
- **Dual-path Claude Code.** Watcher reads both
  `C:\Users\Jim\.claude` and `\\wsl$\Ubuntu\home\jim\.claude`.
