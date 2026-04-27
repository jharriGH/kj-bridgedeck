"""
Session status resolver.

Rules (Bridge-A spec §3):
  processing  → last msg from assistant, no stop_reason yet
  waiting     → stop_reason == 'end_turn'
  needs_input → stop_reason == 'tool_use' with pending tool_use_request
                OR stop_reason == 'max_tokens' mid-task
  idle        → waiting/ended + no activity > `idle_minutes`
  ended       → process dead AND stop_reason present in last message
"""
from __future__ import annotations

from typing import Literal

from watcher.jsonl_parser import JsonlSummary

SessionStatus = Literal["processing", "waiting", "needs_input", "idle", "ended"]


def determine_status(
    summary: JsonlSummary,
    process_alive: bool,
    last_activity_seconds: float,
    idle_after_seconds: float = 10 * 60,
) -> SessionStatus:
    stop = (summary.last_stop_reason or "").lower()
    role = (summary.last_role or "").lower()
    tool_pending = summary.tool_use_pending

    # Ended: process gone AND the last assistant message has a stop_reason
    if not process_alive and stop:
        return "ended"

    # Needs input: the stop_reason is a tool_use handoff, or max_tokens mid-task
    if stop == "tool_use" and tool_pending:
        return "needs_input"
    if stop == "max_tokens":
        return "needs_input"

    # Processing: assistant is mid-turn (no stop_reason yet)
    if role == "assistant" and not stop:
        return "processing"

    # Waiting: assistant finished a turn (end_turn) but process still live
    if stop == "end_turn":
        if process_alive and last_activity_seconds <= idle_after_seconds:
            return "waiting"
        return "idle"

    # Fallback: if the process died and we didn't see a stop_reason, call it ended
    if not process_alive:
        return "ended"

    # Long silence on a live process -> idle
    if last_activity_seconds > idle_after_seconds:
        return "idle"

    return "waiting"
