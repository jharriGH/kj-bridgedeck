"""
Claude Code process discovery.

Uses psutil (not watchdog) per CLAUDE.md rule #4 — file watchers on `\\wsl$`
are unreliable. We poll the process table and correlate to JSONL files by cwd.

Detects both:
  - Native Windows: `claude --dangerously-skip-permissions`
  - WSL2 Ubuntu  : the WSL process appears to psutil as `wsl.exe` with the
                   child command in its cmdline; we also consider bare
                   `claude` / `claude-code` entries in WSL-exposed psutil output.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

import psutil

log = logging.getLogger(__name__)


# Positive markers: if one of these appears, it's almost certainly Claude Code.
_CLAUDE_POSITIVE_MARKERS = (
    "--dangerously-skip-permissions",
    "claude-code",
    "claude.cmd",
    "@anthropic-ai/claude-code",
)

# Negative markers: Electron subprocess flags used by Claude Desktop,
# or helper processes spawned by our own shell.
_CLAUDE_NEGATIVE_MARKERS = (
    "--type=renderer",
    "--type=utility",
    "--type=gpu-process",
    "--type=crashpad-handler",
    "--type=zygote",
    r"\windowsapps\claude_",   # Claude Desktop install path
    r"\tail.exe",               # Claude Code spawns tail for output streaming
    "/tail.exe",
)

# Process names that should never be treated as Claude Code sessions.
_EXCLUDED_PROCESS_NAMES = {
    "bash.exe",
    "sh.exe",
    "zsh.exe",
    "tail.exe",
    "head.exe",
    "cat.exe",
    "grep.exe",
    "git.exe",
    "explorer.exe",
    "code.exe",
    "cursor.exe",
}


def _looks_like_claude_process(cmdline_joined: str, proc_name: str) -> bool:
    lc = cmdline_joined.lower()
    if proc_name.lower() in _EXCLUDED_PROCESS_NAMES:
        return False
    if "claude" not in lc:
        return False
    if any(neg in lc for neg in _CLAUDE_NEGATIVE_MARKERS):
        return False
    return any(marker in lc for marker in _CLAUDE_POSITIVE_MARKERS)


def find_claude_code_processes() -> list[dict[str, Any]]:
    """
    Scan running processes for Claude Code instances.

    Returns a list of dicts with:
        pid, name, cmdline, cwd, create_time, terminal_app, kind
    where kind is "windows" or "wsl".
    """
    found: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "cwd", "create_time", "ppid"]):
        try:
            info = proc.info
            cmdline_list: Iterable[str] = info.get("cmdline") or []
            cmdline = " ".join(cmdline_list)
            if not cmdline:
                continue
            name = info.get("name") or ""
            if not _looks_like_claude_process(cmdline, name):
                continue
            name = name.lower()
            kind = "wsl" if "wsl" in name or "/mnt/" in cmdline or cmdline.startswith("wsl") else "windows"

            terminal_app = _detect_terminal_ancestor(proc)

            found.append(
                {
                    "pid": info.get("pid"),
                    "name": info.get("name"),
                    "cmdline": cmdline,
                    "cwd": info.get("cwd"),
                    "create_time": info.get("create_time"),
                    "terminal_app": terminal_app,
                    "kind": kind,
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception as e:  # noqa: BLE001
            log.debug("process scan skipped pid: %s", e)
            continue
    return found


def _detect_terminal_ancestor(proc: psutil.Process) -> str | None:
    """
    Walk up the parent chain looking for a known terminal host.
    Returns a short label or None.
    """
    known = {
        "windowsterminal.exe": "WindowsTerminal",
        "wt.exe": "WindowsTerminal",
        "cmd.exe": "cmd",
        "powershell.exe": "PowerShell",
        "pwsh.exe": "PowerShell",
        "alacritty.exe": "Alacritty",
        "wezterm-gui.exe": "WezTerm",
        "conhost.exe": "ConsoleHost",
    }
    try:
        walker = proc
        for _ in range(6):  # bounded walk — avoid loops
            parent = walker.parent()
            if parent is None:
                return None
            pname = (parent.name() or "").lower()
            if pname in known:
                return known[pname]
            walker = parent
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None
    return None


def process_alive(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
