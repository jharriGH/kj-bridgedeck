"""
Tmux control for WSL2-hosted Claude Code sessions.

We shell out to `wsl -e tmux ...`; this keeps us from needing a Python tmux
binding inside the Windows interpreter. Everything here is synchronous and
small — callers wrap it in executors when used from async contexts.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from typing import Optional

log = logging.getLogger(__name__)

_WSL = ["wsl", "-e", "tmux"]


def _run(args: list[str], *, check: bool = True, timeout: float = 5.0) -> subprocess.CompletedProcess:
    log.debug("tmux: %s", " ".join(shlex.quote(a) for a in args))
    return subprocess.run(
        args,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def list_tmux_sessions() -> list[str]:
    """Return tmux session names as a list. Empty list if tmux or WSL unavailable."""
    try:
        proc = _run(_WSL + ["ls", "-F", "#S"], check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.debug("list_tmux_sessions failed: %s", e)
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def tmux_session_exists(name: str) -> bool:
    try:
        proc = _run(_WSL + ["has-session", "-t", name], check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def create_tmux_session(name: str, cwd: str, command: Optional[str] = None) -> bool:
    """Create a detached tmux session running an optional command."""
    args = _WSL + ["new-session", "-d", "-s", name, "-c", cwd]
    if command:
        args.append(command)
    try:
        _run(args, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("create_tmux_session %s failed: %s", name, e)
        return False


def send_keys_to_tmux(session_name: str, text: str, submit: bool = True) -> bool:
    """Type `text` into a tmux pane. `submit=True` appends Enter."""
    args = _WSL + ["send-keys", "-t", session_name, text]
    if submit:
        args.append("Enter")
    try:
        _run(args, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("send_keys_to_tmux %s failed: %s", session_name, e)
        return False


def send_signal_to_tmux(session_name: str, key: str) -> bool:
    """
    Send a control key (e.g., 'C-c', 'Escape', 'Enter') without Enter fallthrough.
    """
    try:
        _run(_WSL + ["send-keys", "-t", session_name, key], check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        log.warning("send_signal_to_tmux %s failed: %s", session_name, e)
        return False
