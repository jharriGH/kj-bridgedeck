"""Sessions — dashboard reads + session control proxy to watcher."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from services import history_logger
from services.supabase_client import fetch_all, fetch_one, run_sync, table
from services.watcher_client import WatcherClient
from shared.contracts import SessionLaunchRequest, SessionMessageRequest

router = APIRouter()


@router.get("/live")
async def list_live_sessions() -> list[dict]:
    def _do():
        return (
            table("live_sessions")
            .select("*")
            .neq("status", "ended")
            .order("last_activity", desc=True)
            .execute()
        )
    res = await run_sync(_do)
    return res.data or []


@router.get("/health")
async def session_health() -> dict:
    """Return per-session health classification (healthy / stuck / thrashing /
    expensive) backed by the `session_health_score` view from
    cost_intel_phase2.sql. Returns {"sessions": []} if the view doesn't
    exist yet."""
    def _do():
        return (
            table("session_health_score")
            .select("*")
            .order("total_cost", desc=True)
            .execute()
        )
    try:
        res = await run_sync(_do)
        rows = res.data or []
    except Exception:
        rows = []
    needs_attention = [r for r in rows if r.get("health_status") in ("thrashing", "stuck", "expensive")]
    return {
        "sessions": rows,
        "needs_attention": needs_attention,
        "counts": {
            "thrashing": sum(1 for r in rows if r.get("health_status") == "thrashing"),
            "stuck":     sum(1 for r in rows if r.get("health_status") == "stuck"),
            "expensive": sum(1 for r in rows if r.get("health_status") == "expensive"),
            "healthy":   sum(1 for r in rows if r.get("health_status") == "healthy"),
        },
    }


# Must be ordered BEFORE the /{session_id} catch-all so "recent" does not get
# matched as a session id.
@router.get("/recent")
async def list_recent_sessions(hours: int = 24, limit: int = 200) -> list[dict]:
    """Recent-activity feed for the Monitor. Returns ALL sessions (live or
    ended) whose ``last_activity`` falls within the past ``hours`` window,
    newest-first, capped at ``limit`` rows.

    Complements ``/sessions/live`` which only surfaces non-ended sessions —
    that view is empty whenever nothing is currently running. The Monitor
    uses ``/sessions/recent`` to remain glanceable across quiet moments,
    including quiet ones where nothing is currently running.

    Bounds: ``hours`` clamped to [1, 168] (one week), ``limit`` to [1, 1000].

    NOTE: this route MUST stay declared before ``/{session_id}`` or the
    catch-all UUID matcher will swallow the path.
    """
    hours = max(1, min(int(hours), 168))
    limit = max(1, min(int(limit), 1000))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    def _do():
        return (
            table("live_sessions")
            .select("*")
            .gte("last_activity", cutoff)
            .order("last_activity", desc=True)
            .limit(limit)
            .execute()
        )
    res = await run_sync(_do)
    return res.data or []


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict:
    row = await fetch_one("live_sessions", session_id=session_id)
    if not row:
        archive = await fetch_one("session_archive", session_id=session_id)
        if not archive:
            raise HTTPException(404, f"session {session_id} not found")
        return {"source": "archive", **archive}

    archive = await fetch_one("session_archive", session_id=session_id)
    if archive:
        row["archive"] = archive
    return {"source": "live", **row}


@router.get("/{session_id}/history")
async def session_history(session_id: str) -> list[dict]:
    def _do():
        return (
            table("history_log")
            .select("*")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .execute()
        )
    res = await run_sync(_do)
    return res.data or []


@router.post("/{session_id}/message")
async def send_message(session_id: str, body: SessionMessageRequest) -> dict:
    watcher = WatcherClient()
    result = await watcher.call(
        "POST",
        f"/session/{session_id}/send",
        json=body.model_dump(),
    )
    await history_logger.log(
        event_type="session.message_sent",
        event_category="session",
        actor="api",
        action="send_keys",
        session_id=session_id,
        details={"chars": len(body.text)},
    )
    return result


@router.post("/{session_id}/approve")
async def approve(session_id: str) -> dict:
    watcher = WatcherClient()
    result = await watcher.call("POST", f"/session/{session_id}/approve")
    await history_logger.log(
        event_type="approval.approved",
        event_category="approval",
        actor="api",
        action="approve",
        session_id=session_id,
    )
    return result


@router.post("/{session_id}/reject")
async def reject(session_id: str) -> dict:
    watcher = WatcherClient()
    result = await watcher.call("POST", f"/session/{session_id}/reject")
    await history_logger.log(
        event_type="approval.rejected",
        event_category="approval",
        actor="api",
        action="reject",
        session_id=session_id,
    )
    return result


@router.post("/{session_id}/stop")
async def stop(session_id: str) -> dict:
    watcher = WatcherClient()
    result = await watcher.call("POST", f"/session/{session_id}/stop")
    await history_logger.log(
        event_type="session.stopped",
        event_category="session",
        actor="api",
        action="stop",
        session_id=session_id,
    )
    return result


@router.post("/{session_id}/focus")
async def focus(session_id: str) -> dict:
    watcher = WatcherClient()
    result = await watcher.call("POST", f"/session/{session_id}/focus")
    await history_logger.log(
        event_type="chrome.focus",
        event_category="chrome",
        actor="api",
        action="focus",
        session_id=session_id,
    )
    return result


@router.post("/launch")
async def launch(body: SessionLaunchRequest) -> dict:
    watcher = WatcherClient()
    result = await watcher.call(
        "POST",
        "/session/launch",
        json=body.model_dump(),
    )
    await history_logger.log(
        event_type="launch.requested",
        event_category="launch",
        actor="api",
        action="launch_session",
        project_slug=body.project_slug,
        details={"working_directory": body.working_directory},
    )
    return result
