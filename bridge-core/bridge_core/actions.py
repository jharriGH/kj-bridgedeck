"""ActionExecutor — drains `kjcodedeck.action_queue`.

Runs as a long-lived background task. Started from Bridge-C's FastAPI
`startup` hook (see Bridge-E wiring pass).

Trigger types:
  immediate          run on the next tick
  on_session_end     wait for watch_session_id in live_sessions.status='ended'
  on_schedule        wait for scheduled_for ≤ now
  on_condition       (reserved — evaluates trigger_config predicate)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

ACTION_QUEUE_TABLE = "kjcodedeck.action_queue"
LIVE_SESSIONS_TABLE = "kjcodedeck.live_sessions"


class ActionExecutor:
    def __init__(
        self,
        supabase_client: Any,
        watcher_client: Any,
        brain_client: Any,
        history_logger: Any,
        notes_fn: Any = None,
        interval: int = 15,
    ):
        self.supabase = supabase_client
        self.watcher = watcher_client
        self.brain = brain_client
        self.log = history_logger
        self.notes_fn = notes_fn
        self.interval = interval
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        while self._running:
            try:
                await self._check_condition_triggers()
                await self._process_batch()
            except Exception as exc:
                logger.exception("ActionExecutor loop error: %s", exc)
            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    async def _process_batch(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            q = (
                self.supabase.table(ACTION_QUEUE_TABLE)
                .select("*")
                .eq("status", "queued")
                .eq("trigger_type", "immediate")
                .limit(10)
            )
            rows = await _maybe_await(q.execute())
        except Exception as exc:
            logger.warning("action_queue select failed: %s", exc)
            return

        # Also pull scheduled rows that are due.
        try:
            sched = (
                self.supabase.table(ACTION_QUEUE_TABLE)
                .select("*")
                .eq("status", "queued")
                .eq("trigger_type", "on_schedule")
                .lte("scheduled_for", now_iso)
                .limit(10)
            )
            sched_rows = await _maybe_await(sched.execute())
        except Exception:
            sched_rows = None

        batch = (getattr(rows, "data", None) or []) + (
            getattr(sched_rows, "data", None) or []
        )
        for action in batch:
            await self._execute_one(action)

    async def _execute_one(self, action: dict) -> None:
        action_id = action.get("id")
        try:
            await self._mark(action_id, status="running")
            result = await self._execute(action)
            await self._mark(
                action_id,
                status="completed",
                result=result,
                executed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self._log(action, "success", {"result": result})
        except Exception as exc:
            logger.exception("action %s failed: %s", action.get("action_type"), exc)
            await self._mark(
                action_id,
                status="failed",
                error_message=str(exc),
                executed_at=datetime.now(timezone.utc).isoformat(),
            )
            await self._log(action, "failure", {"error": str(exc)})

    async def _execute(self, action: dict) -> dict:
        action_type = action["action_type"]
        payload = action.get("payload") or {}

        if action_type == "launch_session":
            return await _maybe_await(
                self.watcher.call(
                    "POST",
                    "/sessions/launch",
                    json={
                        "project_slug": action["target_project"],
                        "initial_prompt": payload.get("prompt")
                        or payload.get("initial_prompt"),
                        "working_directory": payload.get("working_directory"),
                    },
                )
            )

        if action_type == "send_message":
            session_id = action["target_session"]
            return await _maybe_await(
                self.watcher.call(
                    "POST",
                    f"/sessions/{session_id}/message",
                    json={"text": payload["text"], "session_id": session_id},
                )
            )

        if action_type == "focus_window":
            session_id = action["target_session"]
            return await _maybe_await(
                self.watcher.call("POST", f"/sessions/{session_id}/focus")
            )

        if action_type == "send_note":
            if self.notes_fn is None:
                raise RuntimeError("notes_fn not configured for send_note action")
            return await _maybe_await(
                self.notes_fn(
                    {
                        "project_slug": action["target_project"],
                        "note_text": payload["text"],
                        "tags": payload.get("tags", []),
                    }
                )
            )

        if action_type == "brain_query":
            return await _maybe_await(self.brain.post_memory(payload))

        if action_type == "custom":
            # Custom actions are a passthrough; handler responsible for dispatch.
            return {"noop": True, "payload": payload}

        raise ValueError(f"Unknown action_type: {action_type}")

    # ------------------------------------------------------------------
    # Conditional triggers
    # ------------------------------------------------------------------

    async def _check_condition_triggers(self) -> None:
        """Promote on_session_end actions to immediate when watched session ends."""
        try:
            q = (
                self.supabase.table(ACTION_QUEUE_TABLE)
                .select("*")
                .eq("status", "queued")
                .eq("trigger_type", "on_session_end")
            )
            waiting = await _maybe_await(q.execute())
        except Exception as exc:
            logger.debug("on_session_end poll failed: %s", exc)
            return

        for action in getattr(waiting, "data", None) or []:
            watch_id = (action.get("trigger_config") or {}).get("watch_session_id")
            if not watch_id:
                continue
            try:
                sq = (
                    self.supabase.table(LIVE_SESSIONS_TABLE)
                    .select("status")
                    .eq("session_id", watch_id)
                    .maybe_single()
                )
                session = await _maybe_await(sq.execute())
            except Exception:
                continue
            data = getattr(session, "data", None)
            if data and data.get("status") == "ended":
                await self._mark(
                    action["id"],
                    trigger_type="immediate",
                    scheduled_for=datetime.now(timezone.utc).isoformat(),
                )

    # ------------------------------------------------------------------
    # Row update helpers
    # ------------------------------------------------------------------

    async def _mark(self, action_id, **updates) -> None:
        if action_id is None or not updates:
            return
        try:
            q = (
                self.supabase.table(ACTION_QUEUE_TABLE)
                .update(updates)
                .eq("id", action_id)
            )
            await _maybe_await(q.execute())
        except Exception as exc:
            logger.warning("action_queue update failed: %s", exc)

    async def _log(self, action: dict, outcome: str, details: dict) -> None:
        if self.log is None:
            return
        try:
            await _maybe_await(
                self.log.log(
                    event_type=f"action_{action['action_type']}",
                    event_category="action",
                    actor="action_executor",
                    action=f"{outcome} {action['action_type']}",
                    outcome=outcome,
                    project_slug=action.get("target_project"),
                    session_id=action.get("target_session"),
                    details=details,
                )
            )
        except Exception as exc:
            logger.debug("history log failed: %s", exc)


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
