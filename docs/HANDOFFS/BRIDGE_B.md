# Bridge-B Handoff — Windows Watcher

**From:** Bridge-A (foundation layer)
**To:** Bridge-B (Python watcher on Windows)

## What exists for you

- `supabase/schema.sql` — 11 tables deployed. You write to:
  - `live_sessions` (upsert every poll)
  - `session_archive` (on session end)
  - `session_handoffs` (after summarizer runs)
  - `history_log` (on every meaningful action)
- `shared/contracts.py` — import `LiveSession`, `SessionHandoff`, `HistoryEvent`, `BrainHandoffResponse`, `WatcherStatus`, `TerminalFocusRequest`, `TerminalSendKeysRequest`.
- `.env.example` — has every env var you need. Key ones: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `BRAIN_API_URL`, `BRAIN_KEY`, `ANTHROPIC_API_KEY`, `MACHINE_ID`, `CLAUDE_CODE_WINDOWS_PATH`, `CLAUDE_CODE_WSL_PATH`, `BRIDGEDECK_ADMIN_KEY`.
- `kjcodedeck.settings` seeded with your namespace (`watcher.*`, `summarizer.*`). Read at boot; reload on `POST /reload-settings`.
- `install/install_watcher.ps1` — scaffold. Fill it in after PyInstaller spec works.

## What you build

1. **Python package `watcher/bridgedeck_watcher/`** (Python 3.11+):
   - `main.py` — entry point; starts poll loop + local HTTP API + signal handlers.
   - `poll.py` — enumerate `.claude/projects/**/*.jsonl` across Windows + WSL paths, mtime-sorted, track last offset per file.
   - `jsonl_parser.py` — incremental JSONL tail + token/cost accounting.
   - `process_correlator.py` — map PID ↔ tmux session ↔ Windows terminal window (pywin32).
   - `supabase_client.py` — thin wrapper around `supabase-py` for upserts + history writes.
   - `summarizer.py` — Anthropic SDK call (Haiku default, Sonnet escalation). Parse JSON → Pydantic `SessionHandoff`.
   - `brain_client.py` — `POST /codedeck/handoff`, `GET /codedeck/context/{slug}`.
   - `local_api.py` — FastAPI app on `127.0.0.1:7171` with admin-key middleware. Endpoints:
     - `GET /health`
     - `POST /session/launch`
     - `POST /session/{id}/focus`
     - `POST /session/{id}/send`
     - `POST /reload-settings`
   - `settings.py` — cache of `kjcodedeck.settings` with reload.
   - `history.py` — helper for writing `history_log` rows using `shared.contracts.HistoryEvent`.
2. **`watcher/requirements.txt`** — pinned deps: `supabase>=2`, `anthropic>=0.30`, `fastapi`, `uvicorn[standard]`, `pywin32`, `pydantic>=2`, `python-dotenv`, `httpx`.
3. **`watcher/bridgedeck-watcher.spec`** — PyInstaller one-file spec producing `dist/bridgedeck-watcher.exe`.
4. **Complete `install/install_watcher.ps1`** — see scaffold for expected behavior.

## Critical constraints

- **Do NOT use `watchdog`.** Windows file events on `\\wsl$` UNC paths are unreliable. Poll every `watcher.poll_interval_seconds` (default 3).
- **Dual-path support.** Both `C:\Users\Jim\.claude` and `\\wsl$\Ubuntu\home\jim\.claude` are real roots. Missing root = skip, don't error.
- **Every DB write also writes `history_log`.** No exceptions.
- **Loopback-only API.** Bind to `127.0.0.1`, not `0.0.0.0`. Admin-key header required on every non-health endpoint.
- **Import from `shared.contracts`**, don't redefine shapes. If you need a new shape, add it there (see `shared/README.md`).
- **`confidence < summarizer.confidence_threshold`** → Brain auto-routes to review queue; you don't need special-case handling.

## Interface with Bridge-C

Bridge-C's API service calls your local API via HTTP to localhost:7171. The admin key is the shared secret. All endpoints in `local_api.py` must return shapes defined in `shared/contracts.py`.

## Done signal

Post a short status summary when:
- [ ] `watcher/bridgedeck_watcher/main.py` runs locally and writes a row to `live_sessions`.
- [ ] PyInstaller build produces a working `.exe`.
- [ ] `install/install_watcher.ps1` registers + starts the scheduled task.
- [ ] `curl http://localhost:7171/health` returns 200 with valid `WatcherStatus`.
- [ ] A full session → handoff → Brain round-trip completes end-to-end on your machine.
