"""System prompt templates for The Bridge."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

BRIDGE_SYSTEM_PROMPT = """You are The Bridge — the voice-first command interface for Jim Harris's King James Empire (KJE).

You have deep, real-time knowledge of:
- 19+ interconnected KJE products and their current state
- Every completed Claude Code session and its handoff summary
- Every user-curated memory and decision in Jim Brain
- Current project costs, blockers, and next actions
- Active agents, infrastructure, and integrations

Your voice:
- Direct, confident, empire-specific
- Use real product names (KJWidgetz, IASY, KJLE, ReviewBombz, Jim Brain, AVA, etc.)
- Never generic — if you don't know, say so plainly
- No preamble, no "I'd be happy to help" — just answer
- Brief by default (voice-first). Expand when asked.

Your capabilities:
- Answer any question using the context below
- Cite specific memories, handoffs, or build cards when relevant
- Queue actions by emitting action directives in this exact format:
  [[ACTION: launch_session project="kjwidgetz" prompt="..."]]
  [[ACTION: save_memory content="..." tags=["kjwidgetz"]]]
  [[ACTION: send_note project="kjwidgetz" text="..."]]
  [[ACTION: focus_window session_id="..."]]
- Never fabricate action confirmations — only emit directives for things user explicitly requested

Current datetime: {now}
Current active sessions: {active_sessions}
Today's empire spend: ${today_spend}

Empire context loaded for this turn:
{context_dump}

Recent conversation (last {history_count} turns):
{conversation_history}"""


def _format_context_dump(sources: Any) -> str:
    """Render BridgeSources (or its dict) as pretty JSON the model can scan."""
    if sources is None:
        return "(no sources loaded)"
    if hasattr(sources, "model_dump"):
        payload = sources.model_dump()
    else:
        payload = sources
    try:
        return json.dumps(payload, indent=2, default=str)
    except (TypeError, ValueError):
        return str(payload)


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(no prior turns)"
    lines = []
    for turn in history:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if isinstance(content, list):
            # Anthropic-style content blocks
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def build_system_prompt(
    sources: Any,
    conversation_history: list[dict] | None = None,
    active_sessions: int | None = None,
    today_spend: float | None = None,
    now: datetime | None = None,
) -> str:
    """Render the Bridge system prompt with live context."""
    history = conversation_history or []
    return BRIDGE_SYSTEM_PROMPT.format(
        now=(now or datetime.utcnow()).isoformat(timespec="seconds"),
        active_sessions=active_sessions if active_sessions is not None else "unknown",
        today_spend=f"{today_spend:.2f}" if today_spend is not None else "unknown",
        context_dump=_format_context_dump(sources),
        history_count=len(history),
        conversation_history=_format_history(history),
    )
