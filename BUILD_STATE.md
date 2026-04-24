# KJ BridgeDeck — Build State

## Version: 0.1.0-alpha

## Parallel build status

- [x] **Bridge-A** (Foundation): Schema, contracts, repo bootstrap — 2026-04-23
- [ ] **Bridge-B** (Watcher): Python watcher on Windows
- [ ] **Bridge-C** (API): FastAPI service on Render
- [ ] **Bridge-D** (Bridge Core): Chat, voice, action executor
- [ ] **Bridge-E** (UI): Standalone HTML + Cloudflare Pages

## Foundation deliverables (Bridge-A, complete)

- [x] `supabase/schema.sql` — 11 tables, indexes, RLS, ~60 seed settings rows
- [x] `shared/contracts.py` — Pydantic models for every cross-agent shape
- [x] `shared/contracts.ts` — TypeScript mirrors
- [x] `render.yaml` — API deployment config
- [x] `install/brain_flush.ps1` — memory queue flush for Task Scheduler
- [x] `install/install_watcher.ps1` — scaffold (Bridge-B fills in)
- [x] `install/install_piper.ps1` — scaffold (Bridge-D fills in)
- [x] `docs/ADMIN_SETTINGS.md` — 13 admin panels catalog
- [x] `docs/HISTORY_LOG.md` — event type catalog
- [x] `docs/DEPLOYMENT.md` — end-to-end deployment runbook
- [x] `docs/HANDOFFS/` — per-agent briefing notes
- [x] `BRIDGEDECK_SPEC.md` — architecture reference
- [x] `CLAUDE.md` — empire context
- [x] `.env.example` — env var template
- [x] `.gitignore`

## Integration points (post-merge verification)

After all agents complete, run end-to-end verification:

- [ ] Schema deployed to Supabase `kjcodedeck` schema (61+ settings rows)
- [ ] Watcher writes to `kjcodedeck.live_sessions` every 3 sec
- [ ] API reads from Supabase and proxies to watcher via localhost:7171
- [ ] Bridge chat streams responses with proper Brain context injection
- [ ] UI loads, records voice via Whisper, renders SSE stream
- [ ] Session end → Haiku summary → Brain handoff → acknowledgement
- [ ] Low-confidence handoff (<0.85) appears in Brain review queue

## Known constraints

- **Windows-first.** User runs Windows 11 with WSL2 Ubuntu available. Installer targets Windows native.
- **Brain v1.4.0 is source of truth** for memory, context, and review queue.
- **No `watchdog` file events** on Windows — poll Claude Code process list every 3 sec.
- **Dual-path Claude Code.** Watcher reads both native `C:\Users\Jim\.claude` and WSL2 `\\wsl$\Ubuntu\home\jim\.claude`.

## Next step after Bridge-A

Jim fires up three PowerShell windows and pastes Bridge-B, Bridge-C, Bridge-D in parallel. Bridge-E follows after those three signal done.
