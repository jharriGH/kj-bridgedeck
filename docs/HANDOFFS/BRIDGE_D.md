# Bridge-D Handoff — Bridge core (chat + voice + actions)

**From:** Bridge-A (foundation layer)
**To:** Bridge-D (the Bridge chat brain + voice + action executor)

## What exists for you

- `shared/contracts.py` — import `BridgeChatRequest`, `BridgeSources`, `ActionDirective`, `QueryIntent`, `BridgeTurn`, `BridgeConversation`.
- `kjcodedeck.bridge_conversations`, `kjcodedeck.bridge_turns` — persistence for chat history.
- `kjcodedeck.action_queue` — where you enqueue structured `ActionDirective`s emitted by the chat.
- `kjcodedeck.settings` namespaces `bridge.*` + `voice.*` — defaults already seeded.
- Bridge-B's local API at `localhost:7171` — your action executor calls it for `launch_session`/`send_message`/`focus_window`.
- Brain API at `https://jim-brain-production.up.railway.app` — your chat uses `GET /codedeck/context/{slug}` and `GET /brain/search?q=` to ground answers.
- `install/install_piper.ps1` — scaffold; you complete it.

## What you build

1. **Python package `bridge-core/bridge/`** (importable by Bridge-C's FastAPI service):
   - `chat.py` — `async def stream_chat(request: BridgeChatRequest) -> AsyncIterator[ChatEvent]`. Handles intent detection, model routing (Haiku by default, Sonnet when intent is `next_action` / `empire_summary` / complex tool use), Brain context injection, system prompt assembly, streaming yield, turn persistence, action extraction.
   - `intent.py` — classify `QueryIntent` via lightweight Haiku call or rule-based heuristics. Returns `QueryIntent` + confidence.
   - `context_builder.py` — given user message + intent, query Brain + Supabase to build `BridgeSources`. Cheap: parallel calls with `asyncio.gather`.
   - `action_parser.py` — parse trailing `<actions>...</actions>` JSON block from assistant response into `list[ActionDirective]`.
   - `executor.py` — background loop that picks `action_queue` rows (`status=queued`, trigger satisfied) and calls watcher/Brain. Updates `result` + `executed_at` + writes `history_log`.
   - `stt.py` — Whisper API client (multipart form, base64 fallback). Settings-driven provider switch.
   - `tts.py` — Piper (subprocess streaming) + ElevenLabs client. Returns audio bytes or streams them.
   - `history.py` — same pattern as Bridge-B/C.
2. **System prompt** — `bridge-core/bridge/prompts/bridge_system.md`. Should:
   - Frame the assistant as "The Bridge" for Jim's empire.
   - List available actions + their JSON schema.
   - Make clear Brain is authoritative; the assistant must not fabricate session info.
   - Instructions to end responses with `<actions>[...]</actions>` when scheduling work.
3. **Complete `install/install_piper.ps1`** — see scaffold.
4. **`bridge-core/requirements.txt`** — `anthropic>=0.30`, `openai>=1.30`, `httpx`, `pydantic>=2`, `supabase>=2`.
5. **Unit tests in `bridge-core/tests/`** — at minimum: intent classification cases, action parser cases, context_builder mock test.

## Critical constraints

- **Never fabricate session state.** Every claim about sessions/costs/projects must come from either Supabase (via a passed-in service) or Brain.
- **Action parser is strict.** If the assistant emits malformed JSON, log + drop the block; do not execute partial actions. History event `error.bridge.action_parse`.
- **Executor respects trigger types.** `on_session_end` means the executor polls the target's live session status until `ended`, *then* runs the payload. Don't run prematurely.
- **Cost accounting per turn.** Every Anthropic call records `tokens_in` + `tokens_out` + `cost_usd` on the `bridge_turns` row and fires `bridge.turn_created` in history.
- **Voice IO is optional.** If `voice.tts_enabled=false`, skip TTS entirely; if Piper binary missing, fall back to web speech (browser-side).
- **Conversation retention.** Prune conversations older than `bridge.conversation_retention_days` in a daily task (can be a scheduled action for M2; not required for MVP).
- **Auto-save to Brain.** After `bridge.auto_save_conversations=true` conversations reach N turns (say 6), call Brain's `POST /memory/save` with the conversation digest. Log `bridge.conversation_saved_to_brain`.

## Interface with Bridge-C

Your `stream_chat` function is imported and wired to `/bridge/chat` SSE. Bridge-C handles HTTP; you handle content. Emit chat events as plain dicts; Bridge-C serializes them to SSE frames.

Your executor runs as a long-lived background task started in Bridge-C's FastAPI startup hook.

## Done signal

- [ ] Voice prompt "empire status" → Whisper → Haiku → streamed response with sources in under 4s.
- [ ] Voice prompt "launch chef-os with prompt X" → assistant confirms → action enqueues → executor invokes watcher → new terminal spawns.
- [ ] Low-intent ("hi") stays Haiku; high-intent ("summarize the last week across the empire") escalates to Sonnet.
- [ ] `install/install_piper.ps1` downloads Piper + voice model + prints paths.
