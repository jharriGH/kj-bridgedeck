"""Sessions — dashboard reads + session control proxy to watcher."""
from __future__ import annotations

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
