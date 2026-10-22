"""
Single-instance guard for the watcher process.

ZOMBIE_GUARD_V1 — a task-scheduler restart must never leave more than one
watcher running. On 2026-10-16 it left eight, each independently polling
and texting Jim. The lock file holds the owning PID; acquisition is atomic
(O_CREAT|O_EXCL) so two processes racing to start at the same instant can't
both believe they won.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import psutil

log = logging.getLogger(__name__)


def _lock_path() -> Path:
    override = os.environ.get("BRIDGEDECK_LOCK_PATH")
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or ".")
    return base / "kj-bridgedeck-watcher.lock"


def _pid_is_watcher(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
        cmdline = " ".join(proc.cmdline()).lower()
        name = (proc.name() or "").lower()
        return "bridgedeck" in cmdline or "bridgedeck" in name or "watcher" in cmdline
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def acquire_or_exit() -> Path:
    """Refuse to start if another watcher instance already holds the lock.

    Call this before any other startup work. Exits the process (status 1)
    if a live watcher already holds the lock — including itself, if it
    loses a startup race to another process. A stale lock (holder PID dead,
    or the PID was reused by something that isn't a watcher) is reclaimed
    automatically. Returns the lock path so the caller can release() it on
    clean shutdown.
    """
    path = _lock_path()
    my_pid = os.getpid()

    if path.exists():
        try:
            holder_pid = int(path.read_text().strip())
        except (ValueError, OSError):
            holder_pid = None
        if holder_pid and holder_pid != my_pid and _pid_is_watcher(holder_pid):
            log.error(
                "Another watcher instance is already running (pid=%d) — "
                "refusing to start (pid=%d).",
                holder_pid, my_pid,
            )
            sys.exit(1)
        log.warning(
            "Reclaiming stale lock file at %s (previous holder pid=%s is gone)",
            path, holder_pid,
        )
        try:
            path.unlink()
        except OSError:
            pass

    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        log.error(
            "Lost startup race to another watcher instance — refusing to start (pid=%d).",
            my_pid,
        )
        sys.exit(1)
    with os.fdopen(fd, "w") as f:
        f.write(str(my_pid))
    log.info("Acquired single-instance lock (pid=%d, path=%s)", my_pid, path)
    return path


def release(path: Path) -> None:
    try:
        if path.exists() and int(path.read_text().strip()) == os.getpid():
            path.unlink()
    except (OSError, ValueError):
        pass
