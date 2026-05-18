"""
Thin Supabase wrapper for writing to the `kjcodedeck` schema.

All write paths also mirror a `history_log` entry — this is non-negotiable per
CLAUDE.md rule #2. Callers that skip the audit row are bugs.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from supabase import Client, create_client

log = logging.getLogger(__name__)

_SCHEMA = "kjcodedeck"
_client: Optional[Client] = None

# WATCHER_AGE_SWEEP_V1 — any live_sessions row whose last_activity is older
# than this threshold is reconciled to status="ended" by sweep_stale_sessions().
# Cross-machine: works for rows we cannot PID-probe (e.g. jim-windows-main from
# a Linux VPS). 48h is conservative — a healthy Claude Code session updates
# last_activity every poll tick (~3s), so anything 2 days silent is a zombie.
STALE_SESSION_MAX_AGE_HOURS = 48


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


# === WATCHER_DURABLE_FIX_V1 (sweep_dead_pid_sessions) ===
def sweep_dead_pid_sessions(machine_id: str) -> int:
    """End any non-ended live_sessions for this machine whose PID is dead.

    Called at watcher startup so stale rows from a previous run (e.g. a
    process that exited while the watcher was interrupted mid-handoff)
    don't pollute /sessions/live. Returns the count of rows ended.

    Uses ``os.kill(pid, 0)`` to probe liveness — fast, no extra deps.
    Skips rows missing a PID. Errors are logged and swallowed; never
    raises out of this function. ``live_sessions`` has no ``ended_at``
    column (that lives on ``session_archive``); status + last_activity
    are the only updateable fields here. (WATCHER_DURABLE_FIX_V1)
    """
    import os
    client = get_supabase()
    if client is None:
        log.warning("sweep_dead_pid_sessions: no supabase client; skipping")
        return 0
    try:
        resp = (
            client.schema(_SCHEMA)
            .table("live_sessions")
            .select("session_id,pid,status")
            .eq("machine_id", machine_id)
            .neq("status", "ended")
            .execute()
        )
        rows = resp.data or []
    except Exception as e:  # noqa: BLE001
        log.warning("sweep_dead_pid_sessions: select failed: %s", e)
        return 0

    ended = 0
    for r in rows:
        pid = r.get("pid")
        sid = r.get("session_id")
        if not pid or not sid:
            continue
        try:
            os.kill(int(pid), 0)
            # Signal 0 = liveness probe. No exception => process alive.
            continue
        except ProcessLookupError:
            pass  # dead — fall through to mark ended
        except PermissionError:
            # Process alive but owned by another user. Treat as alive.
            continue
        except Exception as e:  # noqa: BLE001
            log.debug("sweep_dead_pid_sessions: probe(%s) error: %s — leaving row alone", pid, e)
            continue
        try:
            now = _now_iso()
            client.schema(_SCHEMA).table("live_sessions").update({
                "status": "ended",
                "last_activity": now,
            }).eq("session_id", sid).execute()
            ended += 1
            log.info("sweep_dead_pid_sessions: ended sid=%s pid=%s", sid, pid)
        except Exception as e:  # noqa: BLE001
            log.warning("sweep_dead_pid_sessions: end(%s) failed: %s", sid, e)
    log.info("sweep_dead_pid_sessions(%s): ended %d stale row(s)", machine_id, ended)
    return ended


# === WATCHER_AGE_SWEEP_V1 (sweep_stale_sessions) ===
def sweep_stale_sessions() -> int:
    """End any non-ended live_sessions whose last_activity is older than
    ``STALE_SESSION_MAX_AGE_HOURS``. Cross-machine, age-only, complementary
    to ``sweep_dead_pid_sessions`` (which can only probe local PIDs).

    Specifically targets zombie rows from offline / dead watchers on other
    machines whose PIDs we cannot signal. Returns the count of rows ended.

    Errors all swallowed; never raises. live_sessions has no ``ended_at``
    column — only ``status`` + ``last_activity`` are updateable here.
    (WATCHER_AGE_SWEEP_V1)
    """
    client = get_supabase()
    if client is None:
        log.warning("sweep_stale_sessions: no supabase client; skipping")
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_SESSION_MAX_AGE_HOURS)
    cutoff_iso = cutoff.isoformat()
    try:
        resp = (
            client.schema(_SCHEMA)
            .table("live_sessions")
            .select("session_id,machine_id,status,last_activity")
            .neq("status", "ended")
            .lt("last_activity", cutoff_iso)
            .execute()
        )
        rows = resp.data or []
    except Exception as e:  # noqa: BLE001
        log.warning("sweep_stale_sessions: select failed: %s", e)
        return 0

    if not rows:
        log.debug("sweep_stale_sessions: nothing older than %s", cutoff_iso)
        return 0

    ended = 0
    now = _now_iso()
    for r in rows:
        sid = r.get("session_id")
        if not sid:
            continue
        try:
            client.schema(_SCHEMA).table("live_sessions").update({
                "status": "ended",
                "last_activity": now,
            }).eq("session_id", sid).execute()
            ended += 1
            log.info(
                "sweep_stale_sessions: ended sid=%s machine=%s last_activity=%s",
                sid, r.get("machine_id"), r.get("last_activity"),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("sweep_stale_sessions: end(%s) failed: %s", sid, e)
    log.info(
        "sweep_stale_sessions: ended %d row(s) older than %dh (cutoff=%s)",
        ended, STALE_SESSION_MAX_AGE_HOURS, cutoff_iso,
    )
    return ended


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
