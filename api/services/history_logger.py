"""Centralized history logging. Import and use in every mutating route.

Never throws — failures are logged locally so the originating request
isn't blocked by audit-trail issues.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.supabase_client import insert

logger = logging.getLogger("bridgedeck.api.history")


async def log(
    *,
    event_type: str,
    event_category: str,
    actor: str,
    action: str,
    project_slug: Optional[str] = None,
    session_id: Optional[str] = None,
    target: Optional[str] = None,
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None,
    outcome: str = "success",
    details: Optional[dict] = None,
    cost_usd: Optional[float] = None,
    tokens: Optional[int] = None,
) -> None:
    payload: dict[str, Any] = {
        "event_type": event_type,
        "event_category": event_category,
        "actor": actor,
        "action": action,
        "outcome": outcome,
        "details": details or {},
    }
    if project_slug:
        payload["project_slug"] = project_slug
    if session_id:
        payload["session_id"] = session_id
    if target:
        payload["target"] = target
    if before_state is not None:
        payload["before_state"] = before_state
    if after_state is not None:
        payload["after_state"] = after_state
    if cost_usd is not None:
        payload["cost_usd"] = cost_usd
    if tokens is not None:
        payload["tokens"] = tokens

    try:
        await insert("history_log", payload)
    except Exception as e:
        logger.error("history_log insert failed: %s | payload=%s", e, payload)
