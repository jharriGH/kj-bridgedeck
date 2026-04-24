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
