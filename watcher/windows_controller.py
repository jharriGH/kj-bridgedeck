"""
Native Windows terminal control via pywin32.

Focus a window (SetForegroundWindow), type into it (SendInput). All calls are
best-effort — if pywin32 isn't importable (e.g., running under pytest on Linux
CI), we degrade to log-only no-ops.

Security: per BRIDGEDECK_SPEC §11, we only target HWNDs correlated to PIDs
the watcher itself catalogued. The caller owns that invariant; we just expose
the primitives.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

try:
    import win32api  # type: ignore
    import win32con  # type: ignore
    import win32gui  # type: ignore
    import win32process  # type: ignore

    _PYWIN32_AVAILABLE = True
except ImportError:  # pragma: no cover — Linux dev fallback
    _PYWIN32_AVAILABLE = False
    log.warning("pywin32 unavailable — windows_controller running in no-op mode")


def _require_pywin32() -> bool:
    if not _PYWIN32_AVAILABLE:
        log.warning("windows_controller call ignored: pywin32 missing")
    return _PYWIN32_AVAILABLE


# ============================================================================
# Window discovery
# ============================================================================


def find_windows_for_pid(pid: int) -> list[int]:
    """Return HWNDs whose owning process is `pid`."""
    if not _require_pywin32():
        return []
    hwnds: list[int] = []

    def _cb(hwnd: int, _ctx):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            _, proc_pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:  # noqa: BLE001
            return
        if proc_pid == pid:
            hwnds.append(hwnd)

    win32gui.EnumWindows(_cb, None)
    return hwnds


def _walk_ancestors_for_window(pid: int, max_hops: int = 6) -> list[int]:
    """Walk parent PIDs looking for a visible window (terminal hosts spawn children)."""
    if not _require_pywin32():
        return []
    import psutil  # deferred

    try:
        proc = psutil.Process(pid)
    except psutil.Error:
        return []
    seen = {pid}
    walker = proc
    for _ in range(max_hops):
        hwnds = find_windows_for_pid(walker.pid)
        if hwnds:
            return hwnds
        try:
            walker = walker.parent()
        except psutil.Error:
            return []
        if walker is None or walker.pid in seen:
            return []
        seen.add(walker.pid)
    return []


def find_terminal_window_for_session(session_id: str, pid: int) -> Optional[int]:
    """Return the top-level HWND of the terminal hosting this session, if we can find one."""
    if not _require_pywin32():
        return None
    direct = find_windows_for_pid(pid)
    if direct:
        return direct[0]
    via_ancestors = _walk_ancestors_for_window(pid)
    return via_ancestors[0] if via_ancestors else None


def window_title(hwnd: int) -> str:
    if not _require_pywin32():
        return ""
    try:
        return win32gui.GetWindowText(hwnd) or ""
    except Exception:  # noqa: BLE001
        return ""


# ============================================================================
# Focus + input
# ============================================================================


def focus_window(hwnd: int) -> bool:
    """Bring `hwnd` to the foreground. Returns True on success."""
    if not _require_pywin32():
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("focus_window hwnd=%s failed: %s", hwnd, e)
        return False


def focus_window_by_pid(pid: int) -> bool:
    hwnd = find_terminal_window_for_session("", pid)
    if hwnd is None:
        return False
    return focus_window(hwnd)


def send_keys_to_hwnd(hwnd: int, text: str, submit: bool = True) -> bool:
    """
    Type `text` into `hwnd`. We focus the window first, then use win32api.keybd_event
    for each char (works with terminal apps; SendMessage does not).
    """
    if not _require_pywin32():
        return False
    if not focus_window(hwnd):
        return False
    time.sleep(0.05)
    try:
        for ch in text:
            _type_char(ch)
        if submit:
            _press_key(win32con.VK_RETURN)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("send_keys_to_hwnd failed: %s", e)
        return False


def send_key_by_pid(pid: int, key: str) -> bool:
    """Send a single named key ('enter'|'escape'|'ctrl-c') to the window owning `pid`."""
    if not _require_pywin32():
        return False
    hwnd = find_terminal_window_for_session("", pid)
    if hwnd is None:
        return False
    if not focus_window(hwnd):
        return False
    time.sleep(0.05)
    key = key.lower().strip()
    try:
        if key in ("enter", "return"):
            _press_key(win32con.VK_RETURN)
        elif key == "escape":
            _press_key(win32con.VK_ESCAPE)
        elif key in ("ctrl-c", "ctrl+c", "^c"):
            _press_combo(win32con.VK_CONTROL, ord("C"))
        else:
            return False
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("send_key_by_pid failed: %s", e)
        return False


# ---- internal helpers --------------------------------------------------------


def _type_char(ch: str) -> None:
    # VkKeyScan returns vk in low byte, shift state in high byte
    vk_scan = win32api.VkKeyScan(ch)
    if vk_scan == -1:
        return
    vk = vk_scan & 0xFF
    shift = (vk_scan >> 8) & 1
    if shift:
        win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    if shift:
        win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)


def _press_key(vk: int) -> None:
    win32api.keybd_event(vk, 0, 0, 0)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)


def _press_combo(modifier_vk: int, key_vk: int) -> None:
    win32api.keybd_event(modifier_vk, 0, 0, 0)
    win32api.keybd_event(key_vk, 0, 0, 0)
    win32api.keybd_event(key_vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(modifier_vk, 0, win32con.KEYEVENTF_KEYUP, 0)


# ============================================================================
# Launching new Claude Code sessions in Windows Terminal
# ============================================================================


def launch_windows_terminal_tab(
    cwd: str,
    initial_prompt: Optional[str] = None,
    profile: Optional[str] = None,
) -> bool:
    """
    Open a new Windows Terminal tab, cd to cwd, and spawn Claude Code.
    Uses the `wt` CLI (should be on PATH on any Win10/11 install with Terminal).
    """
    import shlex
    import subprocess

    # wt.exe -w 0 new-tab -d "C:\path" claude --dangerously-skip-permissions "prompt"
    cmd = ["wt.exe", "-w", "0", "new-tab", "-d", cwd]
    if profile:
        cmd += ["-p", profile]
    cmd += ["claude", "--dangerously-skip-permissions"]
    if initial_prompt:
        cmd.append(initial_prompt)
    try:
        subprocess.Popen(cmd, shell=False)
        log.info("wt launched: %s", " ".join(shlex.quote(c) for c in cmd))
        return True
    except (FileNotFoundError, OSError) as e:
        log.warning("launch_windows_terminal_tab failed: %s", e)
        return False
