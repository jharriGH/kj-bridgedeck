# Bridge-C Handoff — FastAPI service on Render

**From:** Bridge-A (foundation layer)
**To:** Bridge-C (FastAPI + Render deploy)

## What exists for you

- `supabase/schema.sql` — 11 tables. You read/write all of them.
- `shared/contracts.py` — import every shape. Use the Pydantic models directly as FastAPI request/response bodies.
- `render.yaml` — already configured. `buildCommand: pip install -r api/requirements.txt`, `startCommand: cd api && uvicorn main:app --host 0.0.0.0 --port $PORT`.
- `.env.example` — env vars you'll need.
- `kjcodedeck.settings` — read on startup; expose a `/admin/reload-settings` endpoint.
- Bridge-B exposes a local HTTP API on `http://localhost:7171` (you proxy to it via `WATCHER_HOST` env).

## What you build

1. **`api/main.py`** — FastAPI app:
   - Startup: load settings from Supabase, init Supabase client, init Brain client, init Anthropic client.
   - CORS: permissive for the Cloudflare Pages origin + `localhost` in dev.
   - Auth middleware: `Authorization: Bearer {BRIDGEDECK_ADMIN_KEY}` on every route except `/health`.
2. **Endpoint modules** (FastAPI routers):
   - `routers/health.py` — `GET /health` (+ Supabase + Brain ping).
   - `routers/sessions.py` — list, get, archive lookup, search.
   - `routers/handoffs.py` — list, search, approve/reject review queue.
   - `routers/notes.py` — CRUD for `session_notes`.
   - `routers/history.py` — filter + paginate `history_log`.
   - `routers/settings.py` — read, update, reload.
   - `routers/auto_approve.py` — CRUD for `auto_approve_rules`.
   - `routers/actions.py` — enqueue + list + cancel; SSE stream for status changes.
   - `routers/projects.py` — list, sync from Brain.
   - `routers/bridge.py` — passthrough to Bridge-D's chat module (see `shared/contracts.py::BridgeChatRequest`).
   - `routers/admin.py` — watcher proxy endpoints (launch session, focus, send).
3. **`api/requirements.txt`** — pinned: `fastapi`, `uvicorn[standard]`, `supabase>=2`, `anthropic>=0.30`, `httpx`, `pydantic>=2`, `python-dotenv`, `sse-starlette`.
4. **`api/services/`** — small modules wrapping Supabase, Brain, Watcher (http to :7171), Anthropic.
5. **`api/history.py`** — same helper pattern as Bridge-B's — every write paths through this.

## Critical constraints

- **Admin-key auth on every mutating endpoint.** Read-only endpoints may skip if surfaced publicly.
- **Never hit Supabase directly from the UI.** UI → API → Supabase. RLS is service-role only, so this is also a technical requirement.
- **Every DB write also writes `history_log`.** Use the helper.
- **Watcher proxy calls** go through `WATCHER_HOST` env var. In prod, this is `http://localhost:7171` (Render isn't colocated with the watcher — this is placeholder until we add Tailscale/Cloudflare Tunnel in M2).
- **Pydantic models come from `shared/contracts.py`**. If you need a new one, add there and mirror in `contracts.ts` — don't define local duplicates.
- **Stream responses for Bridge chat.** Use `sse-starlette` for SSE. Bridge-D provides the streaming generator; you adapt it.

## Endpoint surface (~40+)

Aim for REST-ish: `GET /resource`, `GET /resource/{id}`, `POST /resource`, `PATCH /resource/{id}`, `DELETE /resource/{id}`. See Bridge-E's handoff for the exact UI-facing surface — but Bridge-E builds against what you ship.

## Interface with Bridge-B

- Health check: `GET {WATCHER_HOST}/health` at API startup; surface watcher status in your own `/health`.
- Launch: `POST {WATCHER_HOST}/session/launch` with `SessionLaunchRequest`.
- Focus: `POST {WATCHER_HOST}/session/{id}/focus`.
- Send: `POST {WATCHER_HOST}/session/{id}/send` with `SessionMessageRequest`.

## Interface with Bridge-D

- Bridge-D lives inside this service. Import `bridge-core` as a local package and wire its `stream_chat(request)` into `/bridge/chat` SSE endpoint.
- Shared chat contracts in `shared/contracts.py::BridgeChatRequest` / `BridgeSources` / `ActionDirective`.

## Done signal

- [ ] Render deploy green; `/health` returns 200.
- [ ] Smoke-test: `POST /admin/reload-settings` with admin-key header returns 200.
- [ ] UI-representative fetches (`GET /sessions`, `GET /projects`) return valid shapes.
- [ ] Bridge-D's chat stream reachable via SSE at `/bridge/chat`.
