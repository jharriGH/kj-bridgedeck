"""
Thin Supabase wrapper for writing to the `kjcodedeck` schema.

All write paths also mirror a `history_log` entry — this is non-negotiable per
CLAUDE.md rule #2. Callers that skip the audit row are bugs.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from supabase import Client, create_client

log = logging.getLogger(__name__)

_SCHEMA = "kjcodedeck"
_client: Optional[Client] = None


def get_supabase() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log.warning("SUPABASE_URL / SUPABASE_SERVICE_KEY not set — writes disabled")
        return None
    _client = create_client(url, key)
    return _client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# live_sessions
# ============================================================================


def upsert_live_session(session: dict[str, Any]) -> bool:
    client = get_supabase()
    if client is None:
        return False
    try:
        payload = dict(session)
        payload.setdefault("last_activity", _now_iso())
        client.schema(_SCHEMA).table("live_sessions").upsert(
            payload, on_conflict="session_id"
        ).execute()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("upsert_live_session failed: %s", e)
        return False


def mark_sessions_stale(machine_id: str) -> int:
    """On clean shutdown, flip any non-ended sessions for this machine to idle."""
    client = get_supabase()
    if client is None:
        return 0
    try:
        resp = (
            client.schema(_SCHEMA)
            .table("live_sessions")
            .update({"status": "idle", "last_activity": _now_iso()})
            .eq("machine_id", machine_id)
            .neq("status", "ended")
            .execute()
        )
        return len(resp.data or [])
    except Exception as e:  # noqa: BLE001
        log.warning("mark_sessions_stale failed: %s", e)
        return 0


# ============================================================================
# session_archive + session_handoffs
# ============================================================================


def archive_session(
    session_id: str,
    project_slug: str,
    jsonl_raw: str,
    token_total: int,
    cost_total: float,
    started_at: datetime,
    ended_at: datetime,
) -> bool:
    client = get_supabase()
    if client is None:
        return False
    try:
        client.schema(_SCHEMA).table("session_archive").upsert(
            {
                "session_id": session_id,
                "project_slug": project_slug,
                "jsonl_raw": jsonl_raw,
                "token_total": token_total,
                "cost_total": cost_total,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "archived_at": _now_iso(),
            },
            on_conflict="session_id",
        ).execute()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("archive_session failed: %s", e)
        return False


def insert_handoff(row: dict[str, Any]) -> Optional[str]:
    client = get_supabase()
    if client is None:
        return None
    try:
        resp = client.schema(_SCHEMA).table("session_handoffs").insert(row).execute()
        data = resp.data or []
        return data[0].get("id") if data else None
    except Exception as e:  # noqa: BLE001
        log.warning("insert_handoff failed: %s", e)
        return None


def update_handoff_brain_sync(handoff_id: str, status: str, response: dict | None = None) -> bool:
    client = get_supabase()
    if client is None:
        return False
    try:
        patch: dict[str, Any] = {"brain_sync": status}
        if response is not None:
            patch["brain_response"] = response
        client.schema(_SCHEMA).table("session_handoffs").update(patch).eq(
            "id", handoff_id
        ).execute()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("update_handoff_brain_sync failed: %s", e)
        return False


# ============================================================================
# settings (reads only — writes go through the API admin panel)
# ============================================================================


def fetch_settings() -> list[dict[str, Any]]:
    client = get_supabase()
    if client is None:
        return []
    try:
        return client.schema(_SCHEMA).table("settings").select("*").execute().data or []
    except Exception as e:  # noqa: BLE001
        log.warning("fetch_settings failed: %s", e)
        return []


# ============================================================================
# auto_approve_rules
# ============================================================================


def fetch_auto_approve_rules(project_slug: str) -> list[dict[str, Any]]:
    client = get_supabase()
    if client is None:
        return []
    try:
        return (
            client.schema(_SCHEMA)
            .table("auto_approve_rules")
            .select("*")
            .eq("project_slug", project_slug)
            .eq("enabled", True)
            .execute()
            .data
            or []
        )
    except Exception as e:  # noqa: BLE001
        log.warning("fetch_auto_approve_rules failed: %s", e)
        return []


def bump_auto_approve_rule(rule_id: str) -> bool:
    client = get_supabase()
    if client is None:
        return False
    try:
        # Best effort: increment fire_count via RPC-less update
        existing = (
            client.schema(_SCHEMA)
            .table("auto_approve_rules")
            .select("fire_count")
            .eq("id", rule_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        current = (existing[0].get("fire_count") or 0) if existing else 0
        client.schema(_SCHEMA).table("auto_approve_rules").update(
            {"fire_count": current + 1, "last_fired": _now_iso()}
        ).eq("id", rule_id).execute()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("bump_auto_approve_rule failed: %s", e)
        return False


# ============================================================================
# history_log — used by history_logger.py, exposed here so other modules
# can insert without circular imports.
# ============================================================================


def insert_history_row(row: dict[str, Any]) -> bool:
    client = get_supabase()
    if client is None:
        return False
    try:
        client.schema(_SCHEMA).table("history_log").insert(row).execute()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("insert_history_row failed: %s", e)
        return False
