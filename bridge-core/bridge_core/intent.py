"""Intent classification via Haiku 4.5.

Returns a dict compatible with `QueryIntent` plus optional `project_slug`
and `time_range_days` hints that downstream context-gathering uses to
scope its Brain/Supabase queries.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import AsyncAnthropic

from .utils import strip_code_fence

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

CLASSIFIER_PROMPT = """Classify this user query into exactly one intent.

Query: "{message}"

Intents:
- status_query: asking about current state of a project (blocking issues, progress, health)
- next_action: asking what to work on next
- fact_recall: asking to recall a previously stored fact or decision
- session_history: asking about past CC sessions or recent work
- empire_summary: asking for multi-project or time-range summaries
- cost_query: asking about spending, budget, or token usage
- launch_session: explicit request to start a new Claude Code session
- save_memory: explicit request to remember, save, or record something
- general: none of the above

Output JSON only (no prose, no fences):
{{"intent": "...", "project_slug": "slug_or_null", "time_range_days": number_or_null}}"""


DEFAULT_RESULT: dict[str, Any] = {
    "intent": "general",
    "project_slug": None,
    "time_range_days": None,
}


class IntentRouter:
    """Wraps a Haiku call that classifies the user message."""

    def __init__(self, anthropic_client: AsyncAnthropic, model: str = CLASSIFIER_MODEL):
        self.client = anthropic_client
        self.model = model

    async def classify(self, message: str) -> dict[str, Any]:
        """Returns {'intent', 'project_slug', 'time_range_days'}."""
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=200,
                messages=[
                    {
                        "role": "user",
                        "content": CLASSIFIER_PROMPT.format(message=message),
                    }
                ],
            )
        except Exception as exc:
            logger.warning("intent classify call failed: %s", exc)
            return dict(DEFAULT_RESULT)

        try:
            text = response.content[0].text.strip()
        except (AttributeError, IndexError):
            logger.warning("intent classify: empty response")
            return dict(DEFAULT_RESULT)

        text = strip_code_fence(text)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("intent classify: non-JSON response %r", text[:200])
            return dict(DEFAULT_RESULT)

        return {
            "intent": parsed.get("intent") or "general",
            "project_slug": parsed.get("project_slug") or None,
            "time_range_days": parsed.get("time_range_days"),
        }
