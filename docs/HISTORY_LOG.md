# History Log — Event Catalog

Every write in KJ BridgeDeck produces a `kjcodedeck.history_log` row. This doc catalogs every event type.

## Row shape (recap)

```
id               UUID            -- generated
event_type       TEXT            -- unique string per event (see below)
event_category   TEXT            -- one of 12 enum values
actor            TEXT            -- 'watcher', 'api', 'bridge', 'user', 'brain', 'scheduler'
project_slug     TEXT NULL       -- if event is project-scoped
session_id       TEXT NULL       -- if event is session-scoped
action           TEXT            -- human-readable verb
target           TEXT NULL       -- what the action was against
before_state     JSONB NULL      -- prior state snapshot (if mutation)
after_state      JSONB NULL      -- new state snapshot
outcome          TEXT NULL       -- 'success', 'failure', 'pending', 'cancelled'
details          JSONB           -- freeform context
cost_usd         NUMERIC NULL    -- if event carries cost
tokens           INT NULL        -- if event carries token count
created_at       TIMESTAMPTZ
```

---

## Category: `session`

| Event type | Fires when | Required fields | Notes |
| --- | --- | --- | --- |
| `session.started` | Watcher detects new JSONL + live process | `session_id`, `project_slug`, `actor=watcher` | `after_state` = initial LiveSession |
| `session.status_changed` | Status transitions (e.g., processing → waiting) | `session_id`, `before_state.status`, `after_state.status` | |
| `session.needs_input` | Claude Code prints an approval prompt | `session_id`, `details.prompt_text` | Triggers auto-approve check |
| `session.ended` | Watcher detects process exit | `session_id`, `tokens`, `cost_usd`, `outcome` | |
| `session.archived` | JSONL copied to `session_archive` | `session_id`, `details.byte_count` | |

**Example:**
```json
{
  "event_type": "session.needs_input",
  "event_category": "session",
  "actor": "watcher",
  "project_slug": "chef-os",
  "session_id": "abc123",
  "action": "prompted",
  "target": "user",
  "details": {"prompt_text": "Continue? [1/2]"},
  "outcome": "pending"
}
```

---

## Category: `approval`

| Event type | Fires when | Required fields |
| --- | --- | --- |
| `approval.granted_manual` | User clicks approve in UI | `session_id`, `actor=user` |
| `approval.denied_manual` | User clicks deny | `session_id`, `actor=user` |
| `approval.timed_out` | Prompt sat unanswered past threshold | `session_id`, `details.waited_seconds` |

---

## Category: `bridge`

| Event type | Fires when | Required fields |
| --- | --- | --- |
| `bridge.turn_created` | A new user↔assistant exchange is saved | `details.conversation_id`, `details.turn_id`, `tokens`, `cost_usd` |
| `bridge.conversation_started` | New conversation row created | `details.conversation_id` |
| `bridge.conversation_saved_to_brain` | Auto-save fires | `details.conversation_id`, `details.memory_id_returned` |
| `bridge.action_emitted` | Assistant response contained a queueable action | `details.action_id`, `details.action_type` |

---

## Category: `handoff`

| Event type | Fires when | Required fields |
| --- | --- | --- |
| `handoff.generated` | Summarizer completes | `session_id`, `details.model`, `details.confidence`, `tokens`, `cost_usd` |
| `handoff.posted_to_brain` | POST /codedeck/handoff returns 200 | `session_id`, `details.brain_response` |
| `handoff.rejected_by_brain` | Brain returned non-2xx | `session_id`, `details.error` |
| `handoff.flagged_for_review` | confidence < threshold | `session_id`, `details.confidence` |
| `handoff.retry_scheduled` | Post failed, retry queued | `session_id`, `details.retry_at` |

---

## Category: `budget`

| Event type | Fires when | Required fields |
| --- | --- | --- |
| `budget.warn_threshold_hit` | Spend crossed 80% of cap | `project_slug` or `null` for empire, `cost_usd`, `details.cap` |
| `budget.cap_exceeded` | Spend exceeded cap | `project_slug`, `cost_usd`, `details.cap`, `details.behavior` |
| `budget.soft_pause_applied` | `soft` behavior suspended new launches | `project_slug` |
| `budget.hard_kill_applied` | `hard` behavior killed live sessions | `project_slug`, `details.sessions_killed` |

---

## Category: `action`

| Event type | Fires when | Required fields |
| --- | --- | --- |
| `action.queued` | New row in `action_queue` | `details.action_id`, `details.action_type` |
| `action.started` | Executor picks it up | `details.action_id` |
| `action.completed` | Action finished successfully | `details.action_id`, `outcome=success` |
| `action.failed` | Action errored | `details.action_id`, `details.error`, `outcome=failure` |
| `action.cancelled` | User cancelled before execution | `details.action_id`, `actor=user` |

---

## Category: `setting`

| Event type | Fires when | Required fields |
| --- | --- | --- |
| `setting.updated` | A row in `settings` changed | `target={namespace}.{key}`, `before_state`, `after_state`, `actor` |
| `setting.reloaded` | Component re-read settings | `actor`, `details.component` |

---

## Category: `voice`

| Event type | Fires when | Required fields |
| --- | --- | --- |
| `voice.stt_completed` | Whisper returned text | `details.provider`, `details.duration_sec`, `details.transcript_length` |
| `voice.stt_failed` | STT errored | `details.provider`, `details.error` |
| `voice.tts_played` | Piper/ElevenLabs playback | `details.provider`, `details.text_length` |

---

## Category: `chrome`

| Event type | Fires when | Required fields |
| --- | --- | --- |
| `chrome.window_focused` | Watcher raised a terminal window | `session_id`, `details.window_title` |
| `chrome.keystrokes_injected` | Watcher sent input to a terminal | `session_id`, `details.keys_length`, `details.submit` |
| `chrome.auto_tag_applied` | Title parser matched a project | `session_id`, `project_slug`, `details.rule_pattern` |

---

## Category: `launch`

| Event type | Fires when | Required fields |
| --- | --- | --- |
| `launch.session_requested` | User or Bridge asked for new session | `project_slug`, `actor`, `details.initial_prompt` |
| `launch.session_spawned` | Watcher succeeded | `session_id`, `project_slug`, `details.terminal_app` |
| `launch.session_failed` | Watcher couldn't spawn | `project_slug`, `details.error` |

---

## Category: `auto_approve`

| Event type | Fires when | Required fields |
| --- | --- | --- |
| `auto_approve.fired` | Rule matched + keystroke injected | `session_id`, `project_slug`, `details.rule_id`, `details.pattern` |
| `auto_approve.rate_limited` | Rule matched but hourly quota hit | `session_id`, `details.rule_id`, `details.fires_last_hour` |
| `auto_approve.deny_matched` | Deny rule blocked auto-approval | `session_id`, `details.rule_id` |

---

## Category: `error`

Catch-all for unexpected failures. `event_type` is the component + verb (e.g., `error.watcher.jsonl_parse`, `error.api.supabase_timeout`). Every `error.*` row carries `details.stack`, `details.component`, and `outcome=failure`.

---

## Rule: writing a history event

Every component that mutates state must:

1. Determine the correct `event_category` + `event_type`.
2. Fill `actor` with its own identity (`watcher`, `api`, `bridge`, `scheduler`, or `user` when initiated by a UI action).
3. Capture `before_state` and `after_state` for mutations that replace a row or setting.
4. Populate `cost_usd` + `tokens` if the event consumed Claude/OpenAI credits.
5. Write the row in the same transaction as the underlying change when possible.

Use the `HistoryEvent` Pydantic/TypeScript contract in `shared/contracts.{py,ts}`.
