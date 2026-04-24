# KJ BridgeDeck

Visual terminal management + voice-first command interface for running multiple Claude Code sessions across the Jim Harris / DevelopingRiches empire.

## What it is

**Three tabs, one empire.**

1. **Monitor** — live grid of every Claude Code session across every project (Windows + WSL2), with real-time status, token/cost meters, and approval prompts surfaced in one place.
2. **Terminal** — focus + drive any session remotely: send messages, approve prompts, inject context from Brain.
3. **Bridge** — voice-first chat with a model that has read access to every session handoff, every memory, and every project card in your Brain. Says "launch Chef-OS and ask it to resume the recipe importer" and it happens.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Cloudflare Pages — Standalone HTML + JS UI (Bridge-E)          │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTPS + Bearer
┌────────────────────────▼────────────────────────────────────────┐
│  Render — FastAPI service (Bridge-C)                            │
│  40+ endpoints, Supabase proxy, Brain proxy                     │
└──────┬─────────────────┬─────────────────┬──────────────────────┘
       │ Postgres        │ HTTPS           │ localhost:7171
┌──────▼────────┐ ┌──────▼────────┐ ┌──────▼───────────────────┐
│  Supabase     │ │  Brain API    │ │  Windows Watcher         │
│  kjcodedeck   │ │  v1.4.0       │ │  (Bridge-B)              │
│  11 tables    │ │  Memory/cards │ │  Polls ~/.claude every   │
└───────────────┘ └───────────────┘ │  3 sec, both WSL2 + Win  │
                                    └──────────┬───────────────┘
                                               │
                                    ┌──────────▼───────────────┐
                                    │  Claude Code sessions    │
                                    │  (terminal processes)    │
                                    └──────────────────────────┘
```

Bridge chat (Bridge-D) runs inside the API service, with Piper (local TTS) and Whisper (OpenAI STT) for voice.

## Components

| Path | Owner | Purpose |
| --- | --- | --- |
| `supabase/schema.sql` | Bridge-A | 11 tables: live sessions, archive, handoffs, notes, history log, settings, rules, actions, projects, Bridge conversations/turns |
| `shared/contracts.{py,ts}` | Bridge-A | Single source of truth for cross-agent types |
| `watcher/` | Bridge-B | Python daemon on Windows — polls Claude Code, writes live state, ships JSONL on session end, runs Haiku summarizer, POSTs handoff to Brain |
| `api/` | Bridge-C | FastAPI on Render — every read/write the UI needs |
| `bridge-core/` | Bridge-D | Claude chat with Brain context injection + voice IO + action executor |
| `bridge-ui/` | Bridge-E | Zero-framework HTML + JS dashboard, deployed to Cloudflare Pages |
| `install/` | Bridge-A/B/D | PowerShell scripts for Windows setup |
| `docs/` | Bridge-A | Architecture, settings, event catalog, deployment runbook |

## Quickstart (after full build)

1. Clone + `cp .env.example .env` → fill in keys.
2. Paste `supabase/schema.sql` into Supabase SQL Editor for project `dhzpwobfihrprlcxqjbq`.
3. Deploy API: `render.yaml` auto-picks up via Render GitHub integration.
4. Install watcher on Windows: `pwsh install/install_watcher.ps1`.
5. Install Piper for local TTS: `pwsh install/install_piper.ps1`.
6. Deploy UI to Cloudflare Pages (see `docs/DEPLOYMENT.md`).
7. Open the Pages URL, voice-in: *"empire status"*.

Full runbook: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Status

See [`BUILD_STATE.md`](BUILD_STATE.md). Bridge-A (foundation) is complete; Bridge-B/C/D run in parallel; Bridge-E merges at the end.

## License

Proprietary — DevelopingRiches Inc. All rights reserved.
