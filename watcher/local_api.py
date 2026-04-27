"""
Watcher local HTTP API on localhost:7171.

Consumed by the Bridge-C API service (never exposed publicly — see
BRIDGEDECK_SPEC §11). Admin-key auth is required for every mutating endpoint.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse

from shared.contracts import (
    SessionLaunchRequest,
    SessionMessageRequest,
    WatcherStatus,
)
from watcher import history_logger, tmux_controller, windows_controller
from watcher.config import get_config
from watcher.state import get_state

log = logging.getLogger(__name__)

app = FastAPI(title="KJ BridgeDeck Watcher", version="0.1.0")


# ============================================================================
# Auth
# ============================================================================


def _admin_auth(x_bridgedeck_admin_key: Optional[str] = Header(default=None)) -> None:
    cfg = get_config()
    if not cfg.admin_key:
        return  # dev mode: no key configured -> open
    if x_bridgedeck_admin_key != cfg.admin_key:
        raise HTTPException(status_code=401, detail="invalid admin key")


# ============================================================================
# Read-only
# ============================================================================


@app.get("/health")
def health() -> dict[str, Any]:
    """Unauthenticated — used by install scripts and health checks."""
    state = get_state()
    cfg = get_config()
    return {
        "status": "ok",
        "healthy": True,
        "version": "0.1.0",
        "machine_id": cfg.machine_id,
        "poll_interval": cfg.poll_interval_seconds,
        "active_sessions": state.count(),
        "last_poll": state.last_poll.isoformat() if state.last_poll else None,
        "poll_error": state.poll_error,
    }


@app.get("/status", response_model=WatcherStatus)
def status(_auth: None = Depends(_admin_auth)) -> WatcherStatus:
    state = get_state()
    cfg = get_config()
    return WatcherStatus(
        healthy=state.poll_error is None,
        machine_id=cfg.machine_id,
        poll_interval=cfg.poll_interval_seconds,
        active_sessions=state.count(),
        last_poll=state.last_poll,
        version="0.1.0",
    )


@app.get("/sessions")
def list_sessions(_auth: None = Depends(_admin_auth)) -> dict[str, Any]:
    state = get_state()
    return {"sessions": state.all(), "count": state.count()}


@app.get("/sessions/{session_id}")
def get_session(session_id: str, _auth: None = Depends(_admin_auth)) -> dict[str, Any]:
    session = get_state().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


# ============================================================================
# Mutations
# ============================================================================


def _find_or_404(session_id: str) -> dict[str, Any]:
    session = get_state().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.post("/sessions/{session_id}/message")
def send_message(
    session_id: str,
    req: SessionMessageRequest,
    _auth: None = Depends(_admin_auth),
) -> dict[str, Any]:
    session = _find_or_404(session_id)
    success = _send_text(session, req.text)
    history_logger.quick(
        event_type="session.message_injected",
        event_category="session",
        action="send_text",
        project_slug=session.get("project_slug"),
        session_id=session_id,
        outcome="success" if success else "failure",
        details={"length": len(req.text)},
    )
    if not success:
        raise HTTPException(status_code=500, detail="failed to deliver keystrokes")
    return {"ok": True}


@app.post("/sessions/{session_id}/approve")
def approve(session_id: str, _auth: None = Depends(_admin_auth)) -> dict[str, Any]:
    session = _find_or_404(session_id)
    success = _send_key(session, "enter")
    history_logger.quick(
        event_type="approval.accepted",
        event_category="approval",
        action="approve",
        project_slug=session.get("project_slug"),
        session_id=session_id,
        outcome="success" if success else "failure",
    )
    if not success:
        raise HTTPException(status_code=500, detail="failed to send Enter")
    return {"ok": True}


@app.post("/sessions/{session_id}/reject")
def reject(session_id: str, _auth: None = Depends(_admin_auth)) -> dict[str, Any]:
    session = _find_or_404(session_id)
    success = _send_key(session, "escape")
    history_logger.quick(
        event_type="approval.rejected",
        event_category="approval",
        action="reject",
        project_slug=session.get("project_slug"),
        session_id=session_id,
        outcome="success" if success else "failure",
    )
    if not success:
        raise HTTPException(status_code=500, detail="failed to send Escape")
    return {"ok": True}


@app.post("/sessions/{session_id}/stop")
def stop(session_id: str, _auth: None = Depends(_admin_auth)) -> dict[str, Any]:
    session = _find_or_404(session_id)
    success = _send_key(session, "ctrl-c")
    history_logger.quick(
        event_type="session.stop_sent",
        event_category="session",
        action="stop",
        project_slug=session.get("project_slug"),
        session_id=session_id,
        outcome="success" if success else "failure",
    )
    if not success:
        raise HTTPException(status_code=500, detail="failed to send Ctrl+C")
    return {"ok": True}


@app.post("/sessions/{session_id}/focus")
def focus(session_id: str, _auth: None = Depends(_admin_auth)) -> dict[str, Any]:
    session = _find_or_404(session_id)
    pid = session.get("pid")
    if not pid:
        raise HTTPException(status_code=409, detail="session has no pid")
    success = windows_controller.focus_window_by_pid(int(pid))
    history_logger.quick(
        event_type="chrome.focus_window",
        event_category="chrome",
        action="focus",
        project_slug=session.get("project_slug"),
        session_id=session_id,
        outcome="success" if success else "failure",
    )
    if not success:
        raise HTTPException(status_code=500, detail="focus failed")
    return {"ok": True}


@app.post("/sessions/launch")
def launch(req: SessionLaunchRequest, _auth: None = Depends(_admin_auth)) -> dict[str, Any]:
    cwd = req.working_directory or ""
    if not cwd:
        raise HTTPException(status_code=400, detail="working_directory required")
    success = windows_controller.launch_windows_terminal_tab(cwd, req.initial_prompt)
    history_logger.quick(
        event_type="launch.session",
        event_category="launch",
        action="launch",
        project_slug=req.project_slug,
        outcome="success" if success else "failure",
        details={"cwd": cwd, "has_prompt": bool(req.initial_prompt)},
    )
    if not success:
        raise HTTPException(status_code=500, detail="launch failed")
    return {"ok": True}


@app.post("/reload-settings")
def reload_settings_endpoint(_auth: None = Depends(_admin_auth)) -> dict[str, Any]:
    from watcher.config import reload_settings

    cfg = reload_settings()
    return {"ok": True, "namespaces": list(cfg.raw.keys())}


# ============================================================================
# Internal helpers
# ============================================================================


def _send_text(session: dict[str, Any], text: str) -> bool:
    tmux_name = session.get("tmux_session")
    if tmux_name:
        return tmux_controller.send_keys_to_tmux(tmux_name, text, submit=True)
    pid = session.get("pid")
    if pid:
        hwnd = windows_controller.find_terminal_window_for_session(
            session.get("session_id", ""), int(pid)
        )
        if hwnd is not None:
            return windows_controller.send_keys_to_hwnd(hwnd, text, submit=True)
    return False


def _send_key(session: dict[str, Any], key: str) -> bool:
    tmux_name = session.get("tmux_session")
    if tmux_name:
        if key == "enter":
            return tmux_controller.send_signal_to_tmux(tmux_name, "Enter")
        if key == "escape":
            return tmux_controller.send_signal_to_tmux(tmux_name, "Escape")
        if key == "ctrl-c":
            return tmux_controller.send_signal_to_tmux(tmux_name, "C-c")
        return False
    pid = session.get("pid")
    if pid:
        return windows_controller.send_key_by_pid(int(pid), key)
    return False


# ============================================================================
# Uvicorn server helper (called from main.py)
# ============================================================================


def run_server(host: str = "127.0.0.1", port: int = 7171) -> None:
    """Synchronous entry point if someone wants to run the API alone."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


@app.exception_handler(HTTPException)
async def _http_exception_handler(_req, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
