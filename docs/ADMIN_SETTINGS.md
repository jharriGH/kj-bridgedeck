# Admin Settings Reference

All settings live in `kjcodedeck.settings`. This is the authoritative catalog for every namespace/key, its default, and its allowed values.

Settings are read at component startup and on explicit `POST /admin/reload-settings` calls. There is no hot-reload watcher.

---

## 1. `watcher` — daemon polling + paths

| Key | Default | Type | Description |
| --- | --- | --- | --- |
| `poll_interval_seconds` | `3` | int | How often to poll both Claude Code directories. Lower = faster UI, higher CPU. |
| `claude_code_windows_path` | `"C:\\Users\\Jim\\.claude"` | string | Native-Windows session root. Set `""` to disable. |
| `claude_code_wsl_path` | `"\\\\wsl$\\Ubuntu\\home\\jim\\.claude"` | string | WSL2 session root via UNC. Set `""` to disable. |
| `tmux_prefix` | `"bridgedeck-"` | string | Prefix applied when the watcher launches a tmux-wrapped session. |
| `preferred_terminal` | `"WindowsTerminal"` | enum | One of `WindowsTerminal`, `ConEmu`, `cmd`, `pwsh`. |
| `local_api_port` | `7171` | int | Loopback port for the watcher's HTTP API. |

---

## 2. `summarizer` — session-end Haiku/Sonnet summarizer

| Key | Default | Type | Description |
| --- | --- | --- | --- |
| `model_default` | `"claude-haiku-4-5-20251001"` | string | Primary summarizer (cheap, fast). |
| `model_escalation` | `"claude-sonnet-4-5"` | string | Used when a session exceeds the token threshold. |
| `escalation_token_threshold` | `50000` | int | Tokens in a single session above which Sonnet runs. |
| `confidence_threshold` | `0.85` | float (0–1) | Below this, the handoff is auto-flagged for Brain review. |
| `prompt_version` | `"v1.0"` | string | Current summarizer prompt template version. |

---

## 3. `budget` — empire + per-project cost caps

| Key | Default | Type | Description |
| --- | --- | --- | --- |
| `empire_daily_cap_usd` | `5.00` | float | Aggregate daily USD ceiling across all projects. |
| `empire_weekly_cap_usd` | `30.00` | float | Aggregate weekly USD ceiling. |
| `default_project_daily_cap_usd` | `2.00` | float | Per-project daily cap applied when project has no override. |
| `default_behavior` | `"warn"` | enum | One of `warn` (notify only), `soft` (pause new launches), `hard` (kill in-flight). |
| `warn_threshold_pct` | `80` | int | Emit a budget warning at this percent of the cap. |

---

## 4. `brain` — Brain API integration

| Key | Default | Type | Description |
| --- | --- | --- | --- |
| `api_url` | `"https://jim-brain-production.up.railway.app"` | string | Base URL for Brain v1.4.0. |
| `flush_interval_minutes` | `30` | int | Task Scheduler cadence for `brain_flush.ps1`. Changing this requires updating the scheduled task. |
| `context_depth_default` | `"standard"` | enum | One of `minimal`, `standard`, `deep`. |
| `auto_inject_context` | `true` | bool | On session start, inject Brain context into Claude Code prompt. |

---

## 5. `notifications` — outbound alerts

| Key | Default | Type | Description |
| --- | --- | --- | --- |
| `desktop_enabled` | `true` | bool | Browser desktop notifications. |
| `slack_enabled` | `false` | bool | Enable Slack webhook. |
| `slack_webhook_url` | `""` | string | Slack incoming webhook. |
| `email_enabled` | `false` | bool | Enable email via Resend. |
| `email_to` | `"jim@mobilewebmds.com"` | string | Recipient address. |
| `sms_enabled` | `false` | bool | Enable Twilio SMS. |
| `sms_to` | `""` | string | E.164 phone number. |
| `quiet_hours_start` | `"22:00"` | string (HH:MM) | Silence window start (local TZ). |
| `quiet_hours_end` | `"07:00"` | string (HH:MM) | Silence window end. |
| `events_enabled` | `["needs_input","session_end","budget_warn","budget_kill"]` | string[] | Subset of history event types that trigger alerts. |

---

## 6. `voice` — STT + TTS

| Key | Default | Type | Description |
| --- | --- | --- | --- |
| `stt_provider` | `"whisper_api"` | enum | `whisper_api`, `web_speech`, `whisper_local`. |
| `tts_provider` | `"piper"` | enum | `piper`, `elevenlabs`, `web_speech`. |
| `tts_enabled` | `true` | bool | Read responses aloud. |
| `tts_voice` | `"en_US-ryan-high"` | string | Piper voice model name. |
| `tts_speed` | `1.1` | float | Playback speed multiplier. |
| `push_to_talk` | `true` | bool | If true, user holds a key to talk. |
| `piper_binary_path` | `""` | string | Set after `install/install_piper.ps1` runs. |
| `piper_model_path` | `""` | string | Path to `.onnx` voice model. |

---

## 7. `bridge` — Bridge chat core

| Key | Default | Type | Description |
| --- | --- | --- | --- |
| `default_model` | `"auto"` | enum | `auto` (intent-based), `haiku`, `sonnet`. |
| `haiku_model` | `"claude-haiku-4-5-20251001"` | string | Haiku model ID. |
| `sonnet_model` | `"claude-sonnet-4-5"` | string | Sonnet model ID. |
| `temperature` | `0.7` | float | Generation temperature. |
| `context_depth` | `"standard"` | enum | Depth for Brain context injection per turn. |
| `auto_save_conversations` | `true` | bool | Persist conversations to Brain memory after N turns. |
| `conversation_retention_days` | `90` | int | Conversations older than this are pruned. |

---

## 8. `data` — retention policies

| Key | Default | Type | Description |
| --- | --- | --- | --- |
| `session_archive_retention_days` | `365` | int | JSONL archive lifetime. |
| `history_log_retention_days` | `365` | int | Audit log lifetime. |
| `live_session_cleanup_hours` | `48` | int | Purge `live_sessions` rows in `ended` state after this. |

---

## 9. `appearance` — UI theme

| Key | Default | Type | Description |
| --- | --- | --- | --- |
| `theme` | `"hud_dark"` | enum | `hud_dark`, `hud_light`, `console_green`. |
| `accent_cyan` | `"#00E5FF"` | string | Primary accent (hex). |
| `accent_gold` | `"#FFD700"` | string | Secondary accent. |
| `background` | `"#010810"` | string | Base background. |
| `font_size` | `"14"` | string | Base px. |
| `density` | `"comfortable"` | enum | `compact`, `comfortable`, `spacious`. |
| `default_tab` | `"monitor"` | enum | `monitor`, `terminal`, `bridge`. |

---

## 10. `chrome` — terminal window wrangling

| Key | Default | Type | Description |
| --- | --- | --- | --- |
| `auto_tag_enabled` | `true` | bool | Auto-tag terminal windows with project slug based on title patterns. |
| `focus_behavior` | `"raise_and_activate"` | enum | `raise_only`, `activate_only`, `raise_and_activate`. |
| `title_parse_rules` | `[]` | JSON | Array of `{pattern, project_slug}` regex rules. |

---

## 11. `integrations` — MCP + webhooks

| Key | Default | Type | Description |
| --- | --- | --- | --- |
| `gmail_enabled` | `false` | bool | Gmail MCP available to Bridge chat. |
| `github_enabled` | `false` | bool | GitHub MCP available to Bridge chat. |
| `calendar_enabled` | `false` | bool | Google Calendar MCP. |
| `discord_webhook` | `""` | string | Discord incoming webhook URL. |

---

## 12. `projects` (per-row table, not a namespace)

Stored in `kjcodedeck.projects`. Each project can override `daily_budget_usd`, `weekly_budget_usd`, `budget_behavior`, `auto_approve_enabled`, and `notification_overrides` independently of the empire defaults above.

---

## 13. `auto_approve` (per-row table, not a namespace)

Stored in `kjcodedeck.auto_approve_rules`. Each row is a `pattern` (regex/glob/exact) under one `project_slug`, with `rule_type=allow|deny` and `max_per_hour` rate-limiting. Rules evaluate deny-first, and a match triggers watcher keystroke injection of the default accept option.
