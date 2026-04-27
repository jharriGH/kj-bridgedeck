"""
Haiku 4.5 session summarizer (escalates to Sonnet for long/erroring sessions).

Prompt template is versioned — we keep `summarizer.prompt_version` in Supabase
settings so the UI can show which prompt produced which handoff.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from anthropic import AsyncAnthropic

from watcher.config import get_config

log = logging.getLogger(__name__)


SUMMARIZER_PROMPT_V1 = """You are summarizing a completed Claude Code session for empire memory.

PROJECT: {project_slug}
PROJECT CONTEXT: {project_context}
SESSION DURATION: {duration_minutes} minutes
TOTAL TOKENS: {token_total}
STATUS: {status}

Your job: produce a structured handoff card for Jim Brain (empire's persistent memory).

Read the full conversation JSONL and output JSON:

{{
  "summary": "2-3 sentences. Empire-specific. Product names.",
  "decisions": ["explicit 'we chose X because Y' moments"],
  "artifacts": ["files created/modified/deleted with paths"],
  "next_action": "single sentence — next step in this project",
  "confidence": 0.0 to 1.0 — score LOW if cut off, unclear goals, errors, guessing,
  "warnings": ["unexpected errors, blocking issues, uncertainties"]
}}

Rules:
- NEVER invent decisions or artifacts not in conversation
- Omit file paths if uncertain
- Be empire-specific — use KJWidgetz, Jim Brain, Resend, etc. — not generic
- Confidence below 0.85 routes to review queue
- Aborted sessions still need useful summaries

CONVERSATION:
{jsonl_content}

OUTPUT (JSON only):"""


# Error patterns that should escalate to Sonnet
_ERROR_PATTERNS = (
    r"\btraceback\b",
    r"\berror:",
    r"\bexception\b",
    r"\bfailed to\b",
    r"\bfatal\b",
    r"\bpanic\b",
)


def detect_error_patterns(jsonl_content: str) -> bool:
    lc = jsonl_content.lower()
    return any(re.search(p, lc) for p in _ERROR_PATTERNS)


def choose_summarizer_model(token_total: int, has_errors: bool) -> str:
    cfg = get_config()
    if token_total >= cfg.summarizer_escalation_threshold or has_errors:
        return cfg.summarizer_escalation_model
    return cfg.summarizer_default_model


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        # Remove leading ```json / ```  and trailing ```
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _extract_first_json_object(text: str) -> Optional[dict]:
    """Model occasionally wraps JSON in prose; pull the first balanced {...} block."""
    cleaned = _strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fallback: brace scan
    start = cleaned.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(cleaned[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


async def summarize_session(
    session: dict[str, Any],
    jsonl_content: str,
    project_context: str = "",
) -> dict[str, Any]:
    """
    Returns a dict with keys:
      summary, decisions, artifacts, next_action, confidence, warnings,
      summarizer_model, raw_model_output, prompt_version
    """
    cfg = get_config()
    token_total = int(session.get("tokens_in", 0)) + int(session.get("tokens_out", 0))
    has_errors = detect_error_patterns(jsonl_content)
    model = choose_summarizer_model(token_total, has_errors)

    duration_minutes = session.get("duration_minutes") or 0
    project_slug = session.get("project_slug") or "unknown"
    status = session.get("status") or "completed"

    prompt = SUMMARIZER_PROMPT_V1.format(
        project_slug=project_slug,
        project_context=project_context or "(none)",
        duration_minutes=duration_minutes,
        token_total=token_total,
        status=status,
        jsonl_content=_truncate_for_prompt(jsonl_content),
    )

    api_key = cfg.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY missing; skipping summarizer")
        return _fallback_summary(session, "missing API key")

    client = AsyncAnthropic(api_key=api_key)
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Anthropic summarizer call failed: %s", e)
        return _fallback_summary(session, f"summarizer call failed: {e}")

    text = ""
    try:
        blocks = response.content or []
        for block in blocks:
            if getattr(block, "type", None) == "text":
                text += getattr(block, "text", "")
    except Exception:  # noqa: BLE001
        text = ""

    parsed = _extract_first_json_object(text) or {}
    if not parsed:
        log.warning("Summarizer returned unparseable output — falling back")
        return _fallback_summary(session, "unparseable model output", raw=text)

    parsed.setdefault("summary", "(no summary)")
    parsed.setdefault("decisions", [])
    parsed.setdefault("artifacts", [])
    parsed.setdefault("next_action", None)
    parsed.setdefault("confidence", 0.5)
    parsed.setdefault("warnings", [])
    parsed["summarizer_model"] = model
    parsed["raw_model_output"] = text
    parsed["prompt_version"] = cfg.summarizer_prompt_version
    # Clamp confidence
    try:
        parsed["confidence"] = max(0.0, min(1.0, float(parsed["confidence"])))
    except (TypeError, ValueError):
        parsed["confidence"] = 0.5
    return parsed


def _truncate_for_prompt(content: str, max_chars: int = 180_000) -> str:
    if len(content) <= max_chars:
        return content
    half = max_chars // 2
    return content[:half] + "\n...[truncated]...\n" + content[-half:]


def _fallback_summary(session: dict, reason: str, raw: str = "") -> dict:
    cfg = get_config()
    return {
        "summary": f"(Summarizer unavailable: {reason}) Session {session.get('session_id', '')} on {session.get('project_slug', '')}.",
        "decisions": [],
        "artifacts": [],
        "next_action": None,
        "confidence": 0.0,
        "warnings": [f"fallback_summary: {reason}"],
        "summarizer_model": "fallback",
        "raw_model_output": raw,
        "prompt_version": cfg.summarizer_prompt_version,
    }
