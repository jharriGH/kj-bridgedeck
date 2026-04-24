# KJ BridgeDeck — Architecture Specification

**Version:** 1.0
**Status:** In parallel build (Bridge-A done; B/C/D/E in flight)
**Author:** Bridge-A (foundation)

---

## 1. Product overview

KJ BridgeDeck is a local+cloud control plane that turns every Claude Code session across every Jim Harris / DevelopingRiches project into a single managed surface. It has three tabs:

### 1.1 Monitor
A live grid (updated every 3 seconds) of every Claude Code process across Jim's Windows + WSL2 machines. Each tile shows:

- Project name + emoji (pulled from `kjcodedeck.projects`, seeded from Brain).
- Status chip: `processing` / `waiting` / `needs_input` / `idle` / `ended`.
- Tokens in / out + running cost in USD.
- Elapsed time since `started_at` + time since `last_activity`.
- If `needs_input`: the exact prompt text is surfaced.

Clicking a tile opens the Terminal tab focused on that session.

### 1.2 Terminal
Operator's view of one session: transcript stream, remote input (send text + submit), focus-window button (raises the real terminal on Jim's desktop), inline notes, inline approval for auto-approve matches.

### 1.3 Bridge
Voice-first chat. Hold space to talk → Whisper transcribes → Claude (Haiku by default, Sonnet when the intent is complex) responds with:
- Streaming text.
- Optional Piper TTS playback.
- Zero or more queued actions (launch a session, send a message, save a note, query the Brain). Actions execute after the user confirms, unless the rule is auto-approve.

The Bridge has read access to every handoff, every Brain memory, and every live session in the empire. It's the first place Jim asks "what should I do next?"

---

## 2. Brain integration contract

KJ BridgeDeck never writes to Empire Context, `empire_state`, or Qdrant directly. All writes go through the Brain API.

| Endpoint | Used by | Purpose |
| --- | --- | --- |
| `POST /codedeck/handoff` | Watcher | Send structured session summary at session end |
| `GET /codedeck/context/{slug}?depth=X` | Watcher, Bridge | Fetch context to inject at session start / chat turn |
| `POST /codedeck/flush-memory-queue` | `brain_flush.ps1` scheduled task | Drain pending memory writes every 30 min |
| `GET /brain/search?q=...` | Bridge | Semantic search across Brain cards/memories |
| `GET /brain/project/{slug}` | API (sync) | Refresh cached project metadata |

Handoffs with `confidence < 0.85` land in the Brain review queue automatically. The UI exposes the queue from a simple API read.

---

## 3. Watcher architecture (Bridge-B)

### 3.1 Dual-mode paths

On Jim's Windows machine, Claude Code transcripts land in one of two places:

1. **Native Windows install** → `C:\Users\Jim\.claude\projects\{slug}\{session_id}.jsonl`
2. **WSL2 Ubuntu install** → `\\wsl$\Ubuntu\home\jim\.claude\projects\{slug}\{session_id}.jsonl`

The watcher must enumerate both trees. WSL2 file events over the UNC path are flaky, so the watcher polls (not `watchdog`/inotify).

### 3.2 Poll loop (every `watcher.poll_interval_seconds`, default 3)

1. Enumerate all `*.jsonl` files under both roots, mtime-sorted.
2. For each modified file:
   - Parse incremental JSONL (tail from last offset).
   - Compute rolling status, tokens, cost.
   - Upsert `kjcodedeck.live_sessions` row.
   - If new terminal detected, correlate PID ↔ window title ↔ tmux session.
3. Detect process exit (PID gone OR JSONL untouched for `N` minutes AND last event is terminal).
4. On session end:
   - Archive full JSONL to `kjcodedeck.session_archive`.
   - Run Haiku summarizer (escalate to Sonnet if `tokens > 50k`).
   - Write `kjcodedeck.session_handoffs` row.
   - POST to Brain `/codedeck/handoff`.
   - Update `brain_sync` status from response.
   - Mark live session `status='ended'`.
   - Write `history_log` entry.

### 3.3 Local HTTP API (`:7171`)

FastAPI (or Flask) listening on loopback only. Endpoints:

- `GET /health` → `{healthy: true, version, last_poll, active_sessions}`
- `POST /session/launch` → spawn Windows Terminal with `claude` + optional initial prompt
- `POST /session/{id}/focus` → bring real terminal window to foreground (Win32 `SetForegroundWindow`)
- `POST /session/{id}/send` → type into the terminal (Win32 keystroke injection)
- `POST /reload-settings` → re-read settings from Supabase

Auth: `X-BridgeDeck-Admin-Key` header required. API service (Render) proxies to this over a tunnel or via the user's own machine only — it is never exposed publicly.

---

## 4. Data ownership map

| Table | Primary writer | Readers |
| --- | --- | --- |
| `live_sessions` | Watcher | API, UI (via API) |
| `session_archive` | Watcher | API, UI |
| `session_handoffs` | Watcher | API, UI, Bridge (for context) |
| `session_notes` | API (UI writes) | Watcher (echo to terminal), Bridge |
| `history_log` | Everyone | UI, API (audit views) |
| `settings` | API (admin UI) | Watcher, API, Bridge |
| `auto_approve_rules` | API | Watcher (applies on `needs_input`) |
| `action_queue` | Bridge, API | Bridge executor loop |
| `projects` | API (Brain sync) | Everyone |
| `bridge_conversations` | Bridge | UI |
| `bridge_turns` | Bridge | UI, Bridge (context recall) |

Every write records a `history_log` entry. No exceptions.

---

## 5. Summarizer flow + confidence scoring

On session end, the watcher runs:

1. Slice the JSONL into: opening user message, final user message, decisions extracted from `tool_use` blocks, artifacts (files written), cost totals.
2. Call `claude-haiku-4-5-20251001` with the structured summary prompt (`summarizer.prompt_version`).
3. Expect JSON matching `SessionHandoff` (Pydantic-validated).
4. Compute confidence: 1.0 - (error_count * 0.2) - (ambiguity_flags * 0.1), clamped to [0, 1].
5. If `tokens_in > summarizer.escalation_token_threshold` (default 50k), re-run with Sonnet and keep the higher-confidence result.
6. If confidence < `summarizer.confidence_threshold` (default 0.85), flag the handoff. Brain auto-routes to review queue.
7. POST to Brain. Persist response in `brain_response` JSONB. Update `brain_sync` to `sent`/`failed`/`rejected`.

---

## 6. History log catalog

See `docs/HISTORY_LOG.md` for the full catalog of ~40 event types across 12 categories (`session`, `approval`, `bridge`, `handoff`, `budget`, `action`, `setting`, `voice`, `chrome`, `launch`, `auto_approve`, `error`).

Every event carries: `actor`, `action`, `target`, optional `before_state`/`after_state`, optional `cost_usd`/`tokens`, and always `event_type` + `event_category`.

---

## 7. Admin settings catalog

13 namespaces (`watcher`, `summarizer`, `budget`, `brain`, `notifications`, `voice`, `bridge`, `data`, `appearance`, `chrome`, `integrations` + implicit `projects`, `auto_approve`). See `docs/ADMIN_SETTINGS.md` for every key, default, and description.

Settings are read on component startup + on explicit reload. No hot-reload watching — components call `POST /admin/reload-settings` after edits.

---

## 8. Auto-approve rules

A `needs_input` event triggers:

1. Watcher extracts the prompt text.
2. Query `auto_approve_rules` for `project_slug` + `enabled=true`.
3. Match each rule (regex/glob/exact) against the prompt.
4. Rules evaluate deny-first. Rate-limit check: if `max_per_hour` exceeded, skip.
5. If an allow-rule matches, the watcher sends "1\n" (accept) via keystroke injection; bumps `fire_count` + `last_fired`; logs `auto_approve.fired` in history.
6. If no rule matches (or a deny-rule matches), the prompt surfaces in the UI for Jim to handle manually.

---

## 9. Action queue

The Bridge chat can emit structured `ActionDirective` JSON alongside its text response. The API enqueues them into `action_queue`:

| `trigger_type` | Behavior |
| --- | --- |
| `immediate` | Executor picks it up within 1 poll tick |
| `on_session_end` | Waits for target session's `status` to transition to `ended` |
| `on_schedule` | Waits for `scheduled_for` timestamp |
| `on_condition` | JSONB `trigger_config` holds a predicate evaluated each tick |

Action types: `launch_session`, `send_message`, `focus_window`, `send_note`, `brain_query`, `custom`. Each maps to a call against the Watcher local API or the Brain API.

---

## 10. Deployment topology

- **Supabase** (`dhzpwobfihrprlcxqjbq`, schema `kjcodedeck`) — Postgres + RLS (service-role only).
- **Render** (`kj-bridgedeck-api`) — FastAPI web service, auto-deploy on push.
- **Cloudflare Pages** — Static UI, deploys from `bridge-ui/dist`.
- **Jim's Windows machine** — Watcher (Scheduled Task at logon), Piper binary, Brain flush cron (Scheduled Task every 30 min).
- **Brain** — Railway service `jim-brain-production`, already live.

The Watcher's local HTTP API is **not** exposed publicly. The Render service reaches the watcher only when they're co-located (future: via Tailscale/Cloudflare Tunnel). For MVP, the UI talks only to the Render API, which reads live state from Supabase (populated by the watcher) and sends terminal-control commands via the user's own machine during admin ops.

---

## 11. Security model

- **Supabase** — RLS on all tables, `service_role` for service-to-service only.
- **Brain** — `x-brain-key` header required on every request; key stored in Render + watcher env, never in the UI bundle.
- **BridgeDeck admin key** — Single rotating shared secret for UI → API and API → Watcher. Kept out of git; stored in Render env + Windows DPAPI-encrypted file for the watcher.
- **Voice** — Audio is sent to OpenAI Whisper (transitory); nothing persisted beyond `bridge_turns.voice_input` flag.
- **Keystroke injection** — Only loopback-authenticated calls can trigger terminal writes, and only for PIDs the watcher itself catalogued. No arbitrary window targeting.
- **Cost guardrails** — `budget` settings enforce hard/soft/warn caps per project and empire-wide. Breaching a hard cap cancels in-flight queued actions and flips affected projects to read-only in the UI.
