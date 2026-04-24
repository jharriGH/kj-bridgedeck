# Bridge-E Handoff — Standalone UI

**From:** Bridge-A (foundation layer)
**To:** Bridge-E (Cloudflare Pages frontend — runs last)

## Prerequisites before you start

Bridge-B, C, D must be **done**. Specifically:
- Bridge-C's API is live on Render and responding at the URL in `.env::API_PUBLIC_URL`.
- Bridge-C's SSE endpoint `/bridge/chat` streams properly.
- Bridge-B's watcher is running on Jim's Windows machine and writing `live_sessions`.

## What exists for you

- `shared/contracts.ts` — import every shape. This is your type ground truth.
- Bridge-C provides `~40` REST endpoints + `/bridge/chat` SSE.
- `kjcodedeck.settings::appearance.*` — theme, colors, density, default tab. Read via `GET /settings?namespace=appearance`.

## What you build

1. **`bridge-ui/`** — standalone HTML/JS (or Vite + Preact/Solid if you prefer). Keep it light — this is a dashboard, not an app.
2. **Three tabs:**
   - **Monitor** — Live grid of tiles, one per session. Polls `GET /sessions` every 3 sec or subscribes to an SSE feed if Bridge-C exposes one. Status chips color-coded.
   - **Terminal** — focused single-session view with transcript, remote input, focus button, inline notes.
   - **Bridge** — voice-first chat UI. Hold-space to talk → Whisper (Bridge-C endpoint) → stream assistant response → optional Piper audio playback. Queued actions appear as cards with approve/cancel.
3. **Admin panel** — 13 accordion sections mirroring `docs/ADMIN_SETTINGS.md`. Each form posts back to `PATCH /settings/{namespace}/{key}`.
4. **Cloudflare Pages deploy config** — see `docs/DEPLOYMENT.md::7`.

## Critical constraints

- **UI never calls Supabase directly.** Every read/write goes through the Render API.
- **Admin key** is a single shared secret; it belongs in a Cloudflare Pages env var, not in a public bundle. Use the `VITE_ADMIN_KEY` prefix + the Worker-side proxy pattern if you want real secrecy. For MVP, a private Pages deploy with the key inlined is acceptable.
- **Theme values drive CSS variables.** Read `appearance.*` once at boot + after every settings change.
- **Import from `shared/contracts.ts`.** If you need a new shape, add there and mirror in `contracts.py`.

## Done signal

- [ ] Monitor tab lists every active session and refreshes in near-real-time.
- [ ] Terminal tab sends messages into a real Claude Code session on Jim's Windows machine.
- [ ] Bridge tab accepts voice, streams response, plays Piper TTS, and queues actions that actually execute.
- [ ] Admin panel can change a setting and the change propagates to the watcher after `POST /admin/reload-settings`.
- [ ] Cloudflare Pages deploy is live; UI loads in under 2s on a cold hit.
