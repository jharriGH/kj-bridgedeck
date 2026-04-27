"""Small shared helpers for bridge_core."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("bridge_core")


def now_iso() -> str:
    """UTC now as ISO-8601 string (timezone aware)."""
    return datetime.now(timezone.utc).isoformat()


def safe_json_loads(text: str, default: Any = None) -> Any:
    """json.loads that swallows errors and returns `default` instead."""
    import json

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def strip_code_fence(text: str) -> str:
    """Strip ```json ... ``` wrappers emitted by some models."""
    s = text.strip()
    if s.startswith("```"):
        # Drop the opening fence (optionally with language tag) and trailing fence.
        s = s.split("```", 2)
        # shape after split: ["", "json\n{...}", ""] or ["", "{...}", ""]
        if len(s) >= 2:
            body = s[1]
            for tag in ("json", "JSON"):
                if body.lstrip().startswith(tag):
                    body = body.lstrip()[len(tag):]
                    break
            return body.strip()
    return s
