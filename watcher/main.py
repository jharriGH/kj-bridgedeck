"""
KJ BridgeDeck Watcher — entry point.

Startup:
  1. Load settings from Supabase (best-effort; falls back to env defaults)
  2. Launch local_api (FastAPI on :7171) on a background thread
  3. Begin the 3-second polling loop

Each loop tick:
  1. Detect Claude Code processes
  2. For each, resolve its active JSONL and parse the tail
  3. Determine status; upsert kjcodedeck.live_sessions
  4. If status changed → history_log
  5. If needs_input + auto-approve rule allows → fire
  6. If ended → archive + summarize + POST handoff to Brain

Shutdown (SIGINT/SIGTERM):
  - Cancel the poll loop
  - Flush pending handoffs (best-effort)
  - Mark this machine's non-ended sessions as stale
  - Exit cleanly
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Allow running as `python watcher/main.py` or `python -m watcher.main`
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.contracts import SessionHandoff  # noqa: E402

from watcher import (  # noqa: E402
    auto_approve,
    brain_client,
    cost_calculator,
    history_logger,
    jsonl_parser,
    process_detector,
    status_resolver,
    summarizer,
    supabase_client,
)
from watcher.config import get_config, reload_settings  # noqa: E402
from watcher.state import get_state  # noqa: E402


log = logging.getLogger("bridgedeck.watcher")


# ============================================================================
# Per-session tracking (in-memory)
# ============================================================================


class _SessionTracker:
    """Holds state we care about between ticks — not everything needs Supabase."""

    def __init__(self) -> None:
        self.last_status: dict[str, str] = {}
        self.started_at: dict[str, datetime] = {}
        self.last_jsonl_path: dict[str, str] = {}
        self.last_activity: dict[str, datetime] = {}
        self.pid_for_session: dict[str, int] = {}


_tracker = _SessionTracker()


# ============================================================================
# Session id derivation — we want stable IDs across polls
# ============================================================================


def _derive_session_id(jsonl_path: Optional[Path], pid: int, cwd: Optional[str]) -> str:
    """
    Prefer the JSONL filename stem (it's a UUID minted by Claude Code).
    Fall back to a deterministic hash of pid+cwd so we never generate
    a new id for the same tracked process.
    """
    if jsonl_path is not None:
        return jsonl_path.stem
    seed = f"{pid}|{cwd or ''}"
    return "nojsonl-" + hashlib.sha1(seed.encode()).hexdigest()[:16]


# ============================================================================
# One tick
# ============================================================================


async def poll_once() -> None:
    cfg = get_config()
    state = get_state()
    now = datetime.now(timezone.utc)

    try:
        procs = process_detector.find_claude_code_processes()
    except Exception as e:  # noqa: BLE001
        log.warning("process scan failed: %s", e)
        state.mark_poll_error(str(e))
        return

    data_paths = jsonl_parser.resolve_claude_data_paths(
        cfg.claude_windows_path, cfg.claude_wsl_path
    )

    seen_sessions: set[str] = set()

    for proc in procs:
        pid = proc["pid"]
        cwd = proc.get("cwd")
        jsonl_path = jsonl_parser.find_active_jsonl(cwd, data_paths)
        session_id = _derive_session_id(jsonl_path, pid, cwd)
        seen_sessions.add(session_id)

        summary = jsonl_parser.summarize_jsonl(jsonl_path) if jsonl_path else None

        # Started-at: use the earliest we've seen
        started = _tracker.started_at.get(session_id)
        if started is None:
            started = datetime.fromtimestamp(proc.get("create_time") or now.timestamp(), tz=timezone.utc)
            _tracker.started_at[session_id] = started
        _tracker.pid_for_session[session_id] = pid

        # Last activity: JSONL mtime if present, else proc create time
        last_activity_dt = now
        if summary and summary.last_mtime:
            last_activity_dt = datetime.fromtimestamp(summary.last_mtime, tz=timezone.utc)
        _tracker.last_activity[session_id] = last_activity_dt
        activity_seconds = (now - last_activity_dt).total_seconds()

        # Status
        proc_alive = process_detector.process_alive(pid)
        if summary is not None:
            status = status_resolver.determine_status(
                summary, proc_alive, activity_seconds,
                idle_after_seconds=cfg.idle_minutes * 60,
            )
            tokens_in = summary.tokens_in
            tokens_out = summary.tokens_out
            model = summary.model
            needs_input_msg = summary.last_message_text if status == "needs_input" else None
        else:
            # No JSONL yet — call it processing while alive, idle otherwise
            status = "processing" if proc_alive else "idle"
            tokens_in = 0
            tokens_out = 0
            model = None
            needs_input_msg = None

        project_slug = _derive_project_slug(cwd)
        cost = cost_calculator.calculate_cost(model, tokens_in, tokens_out)

        row: dict[str, Any] = {
            "session_id": session_id,
            "project_slug": project_slug,
            "machine_id": cfg.machine_id,
            "pid": pid,
            "cwd": cwd,
            "terminal_app": proc.get("terminal_app"),
            "window_title": None,
            "tmux_session": None,
            "status": status,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost,
            "started_at": started.isoformat(),
            "last_activity": last_activity_dt.isoformat(),
            "jsonl_path": str(jsonl_path) if jsonl_path else None,
            "needs_input_msg": needs_input_msg,
            "metadata": {"kind": proc.get("kind")},
        }

        supabase_client.upsert_live_session(row)
        state.upsert(session_id, row)
        if jsonl_path is not None:
            _tracker.last_jsonl_path[session_id] = str(jsonl_path)

        # Status transition logging
        prev_status = _tracker.last_status.get(session_id)
        if prev_status != status:
            _tracker.last_status[session_id] = status
            history_logger.quick(
                event_type=f"session.{status}",
                event_category="session",
                action="status_change",
                project_slug=project_slug,
                session_id=session_id,
                before_state={"status": prev_status} if prev_status else None,
                after_state={"status": status},
                outcome="success",
                tokens=tokens_in + tokens_out,
                cost_usd=cost,
            )

        # Auto-approve on needs_input
        if status == "needs_input" and needs_input_msg:
            try:
                result = auto_approve.match_and_fire(row, needs_input_msg)
                if result:
                    log.info("auto_approve: %s for %s", result, session_id)
            except Exception as e:  # noqa: BLE001
                log.warning("auto_approve failed: %s", e)

    # Detect ended sessions: tracked before, not seen this tick
    previously_tracked = set(_tracker.last_status.keys())
    gone = previously_tracked - seen_sessions
    for session_id in gone:
        await _handle_session_end(session_id)

    state.mark_poll()


def _derive_project_slug(cwd: Optional[str]) -> str:
    if not cwd:
        return "unknown"
    base = os.path.basename(cwd.rstrip("/\\"))
    return base or "unknown"


# ============================================================================
# End-of-session archival + Brain handoff
# ============================================================================


async def _handle_session_end(session_id: str) -> None:
    state = get_state()
    snapshot = state.get(session_id)
    if snapshot is None:
        _tracker.last_status.pop(session_id, None)
        return

    status = snapshot.get("status") or "ended"
    jsonl_path = _tracker.last_jsonl_path.get(session_id)
    started = _tracker.started_at.get(session_id) or datetime.now(timezone.utc)
    ended = datetime.now(timezone.utc)
    duration_minutes = max(0.0, (ended - started).total_seconds() / 60.0)

    project_slug = snapshot.get("project_slug", "unknown")
    tokens_in = int(snapshot.get("tokens_in") or 0)
    tokens_out = int(snapshot.get("tokens_out") or 0)
    total_tokens = tokens_in + tokens_out
    cost = float(snapshot.get("cost_usd") or 0.0)

    # 1) Archive raw JSONL
    jsonl_content = ""
    if jsonl_path and Path(jsonl_path).exists():
        jsonl_content = jsonl_parser.read_full_jsonl(Path(jsonl_path))
        supabase_client.archive_session(
            session_id=session_id,
            project_slug=project_slug,
            jsonl_raw=jsonl_content,
            token_total=total_tokens,
            cost_total=cost,
            started_at=started,
            ended_at=ended,
        )

    # 2) Summarize
    handoff_status = _handoff_status_for(status, jsonl_content)
    summary = await summarizer.summarize_session(
        {
            "session_id": session_id,
            "project_slug": project_slug,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "duration_minutes": round(duration_minutes, 1),
            "status": handoff_status,
        },
        jsonl_content,
    )

    # 3) Insert handoff row
    handoff_row = {
        "session_id": session_id,
        "project_slug": project_slug,
        "summary": summary.get("summary") or "",
        "decisions": summary.get("decisions") or [],
        "artifacts": summary.get("artifacts") or [],
        "next_action": summary.get("next_action"),
        "token_cost": cost,
        "confidence": summary.get("confidence") or 0.0,
        "status": handoff_status,
        "summarizer_model": summary.get("summarizer_model"),
        "brain_sync": "pending",
    }
    handoff_id = supabase_client.insert_handoff(handoff_row)

    # 4) POST to Brain
    brain_response_dict: Optional[dict] = None
    brain_sync_status = "failed"
    try:
        handoff = SessionHandoff(
            project_slug=project_slug,
            summary=handoff_row["summary"],
            decisions=handoff_row["decisions"],
            artifacts=handoff_row["artifacts"],
            next_action=handoff_row["next_action"],
            token_cost=cost,
            session_id=session_id,
            confidence=handoff_row["confidence"],
            agent="codedeck_watcher",
            status=handoff_status,
        )
        resp = await brain_client.BrainClient().send_handoff(handoff)
        brain_response_dict = resp.model_dump()
        brain_sync_status = "sent"
    except Exception as e:  # noqa: BLE001
        log.warning("Brain handoff failed for %s: %s", session_id, e)
        brain_response_dict = {"error": str(e)}
        brain_sync_status = "failed"

    if handoff_id:
        supabase_client.update_handoff_brain_sync(handoff_id, brain_sync_status, brain_response_dict)

    # 5) Flip live session to ended
    snapshot["status"] = "ended"
    supabase_client.upsert_live_session(snapshot)
    state.remove(session_id)

    history_logger.quick(
        event_type="handoff.sent" if brain_sync_status == "sent" else "handoff.failed",
        event_category="handoff",
        action="handoff",
        project_slug=project_slug,
        session_id=session_id,
        outcome="success" if brain_sync_status == "sent" else "failure",
        tokens=total_tokens,
        cost_usd=cost,
        details={
            "confidence": summary.get("confidence"),
            "summarizer_model": summary.get("summarizer_model"),
            "handoff_status": handoff_status,
        },
    )

    # 6) Cleanup tracker
    _tracker.last_status.pop(session_id, None)
    _tracker.started_at.pop(session_id, None)
    _tracker.last_jsonl_path.pop(session_id, None)
    _tracker.last_activity.pop(session_id, None)
    _tracker.pid_for_session.pop(session_id, None)


def _handoff_status_for(status: str, jsonl_content: str) -> str:
    if status in ("ended", "waiting") and not summarizer.detect_error_patterns(jsonl_content):
        return "completed"
    if not jsonl_content or len(jsonl_content) < 200:
        return "aborted"
    return "partial"


# ============================================================================
# Local API runner
# ============================================================================


def _start_local_api_thread() -> threading.Thread:
    import uvicorn

    cfg = get_config()

    def _runner() -> None:
        from watcher.local_api import app as fastapi_app

        config = uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=cfg.local_api_port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        try:
            server.run()
        except Exception as e:  # noqa: BLE001
            log.error("local_api server crashed: %s", e)

    t = threading.Thread(target=_runner, name="bridgedeck-local-api", daemon=True)
    t.start()
    return t


# ============================================================================
# Main loop + lifecycle
# ============================================================================


async def run() -> None:
    cfg = reload_settings()
    log.info("Watcher starting — machine_id=%s port=%s", cfg.machine_id, cfg.local_api_port)
    _start_local_api_thread()

    history_logger.quick(
        event_type="watcher.started",
        event_category="session",
        action="start",
        outcome="success",
        details={"machine_id": cfg.machine_id, "version": "0.1.0"},
    )

    stop_event = asyncio.Event()

    def _request_stop(*_: object) -> None:
        log.info("Shutdown signal received")
        stop_event.set()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_stop)
            except NotImplementedError:
                # Windows: add_signal_handler is limited; signal.signal works for SIGINT
                signal.signal(sig, lambda *_a: _request_stop())
    except Exception as e:  # noqa: BLE001
        log.debug("Could not install signal handlers: %s", e)

    while not stop_event.is_set():
        try:
            await poll_once()
        except Exception as e:  # noqa: BLE001
            log.exception("poll_once crashed: %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=cfg.poll_interval_seconds)
        except asyncio.TimeoutError:
            pass

    await _shutdown()


async def _shutdown() -> None:
    cfg = get_config()
    log.info("Flushing pending handoffs and marking sessions stale")
    # Flush: process any tracked sessions as if they ended
    tracked = list(_tracker.last_status.keys())
    for sid in tracked:
        try:
            await _handle_session_end(sid)
        except Exception as e:  # noqa: BLE001
            log.warning("shutdown flush failed for %s: %s", sid, e)
    supabase_client.mark_sessions_stale(cfg.machine_id)
    history_logger.quick(
        event_type="watcher.stopped",
        event_category="session",
        action="stop",
        outcome="success",
        details={"machine_id": cfg.machine_id},
    )


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("BRIDGEDECK_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def cli() -> None:
    _configure_logging()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
