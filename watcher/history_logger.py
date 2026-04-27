"""
history_log writer. Never throws — logs internally on failure.

Per CLAUDE.md rule #2, every DB-mutating action from the watcher must also
emit a history_log entry. This module is intentionally boring.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from shared.contracts import HistoryEvent

from watcher import supabase_client

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def log_event(event: HistoryEvent) -> None:
    """Async-friendly wrapper. Never raises."""
    log_event_sync(event)


def log_event_sync(event: HistoryEvent) -> None:
    try:
        row = event.model_dump(mode="json", exclude_none=True)
        row.setdefault("created_at", _now_iso())
        supabase_client.insert_history_row(row)
    except Exception as e:  # noqa: BLE001
        log.warning("history_logger failed to write event: %s", e)


def quick(
    event_type: str,
    event_category: str,
    action: str,
    *,
    project_slug: Optional[str] = None,
    session_id: Optional[str] = None,
    target: Optional[str] = None,
    outcome: Optional[str] = None,
    details: Optional[dict] = None,
    cost_usd: Optional[float] = None,
    tokens: Optional[int] = None,
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None,
    actor: str = "codedeck_watcher",
) -> None:
    """Convenience helper — build HistoryEvent + insert in one call."""
    try:
        event = HistoryEvent(
            event_type=event_type,
            event_category=event_category,  # type: ignore[arg-type]
            actor=actor,
            project_slug=project_slug,
            session_id=session_id,
            action=action,
            target=target,
            before_state=before_state,
            after_state=after_state,
            outcome=outcome,  # type: ignore[arg-type]
            details=details or {},
            cost_usd=cost_usd,
            tokens=tokens,
        )
        log_event_sync(event)
    except Exception as e:  # noqa: BLE001
        log.warning("history_logger.quick failed: %s", e)
