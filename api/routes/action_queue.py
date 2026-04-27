"""Action queue — Bridge-scheduled actions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from services import history_logger
from services.supabase_client import (
    delete as sb_delete,
    fetch_one,
    insert,
    run_sync,
    table,
    update as sb_update,
)
from shared.contracts import QueuedAction

router = APIRouter()


@router.get("")
async def list_pending() -> list[dict]:
    def _do():
        return (
            table("action_queue")
            .select("*")
            .in_("status", ["queued", "running"])
            .order("created_at", desc=True)
            .execute()
        )
    res = await run_sync(_do)
    return res.data or []


@router.get("/history")
async def list_history(limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    def _do():
        return (
            table("action_queue")
            .select("*")
            .in_("status", ["completed", "failed", "cancelled"])
            .order("executed_at", desc=True)
            .limit(limit)
            .execute()
        )
    res = await run_sync(_do)
    return res.data or []


@router.get("/{action_id}")
async def get_action(action_id: str) -> dict:
    row = await fetch_one("action_queue", id=action_id)
    if not row:
        raise HTTPException(404, f"action {action_id} not found")
    return row


@router.post("")
async def queue_action(action: QueuedAction) -> dict:
    payload = action.model_dump(exclude={"id", "executed_at", "result", "error_message"})
    rows = await insert("action_queue", payload)
    if not rows:
        raise HTTPException(500, "action insert returned no row")
    new_action = rows[0]
    await history_logger.log(
        event_type="action.queued",
        event_category="action",
        actor="api",
        action="queue_action",
        project_slug=action.target_project,
        session_id=action.target_session,
        target=new_action["id"],
        details={"action_type": action.action_type, "trigger_type": action.trigger_type},
    )
    return new_action


@router.delete("/{action_id}")
async def cancel_action(action_id: str) -> dict:
    existing = await fetch_one("action_queue", id=action_id)
    if not existing:
        raise HTTPException(404, f"action {action_id} not found")
    if existing["status"] != "queued":
        raise HTTPException(
            409,
            f"cannot cancel action in status '{existing['status']}'",
        )
    await sb_update("action_queue", {"status": "cancelled"}, id=action_id)
    await history_logger.log(
        event_type="action.cancelled",
        event_category="action",
        actor="api",
        action="cancel_action",
        target=action_id,
        before_state={"status": "queued"},
        after_state={"status": "cancelled"},
    )
    return {"ok": True, "cancelled": action_id}
