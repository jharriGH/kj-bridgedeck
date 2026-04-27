"""
Claude Code JSONL transcript reader.

Both native Windows and WSL2 installs store transcripts under
`~/.claude/projects/{slug}/...`. The exact subpath varies by client version —
sometimes `conversations/{uuid}.jsonl`, sometimes directly `{uuid}.jsonl` at
the project root. We glob defensively and mtime-sort.

Keep this module I/O-light: parse only the tail of each JSONL for polling.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger(__name__)


# ============================================================================
# Path resolution
# ============================================================================


def resolve_claude_data_paths(
    windows_path: str | None, wsl_path: str | None
) -> list[Path]:
    """Return all Claude data directories that currently exist on disk."""
    candidates: list[Path] = []
    for raw in (windows_path, wsl_path):
        if not raw:
            continue
        try:
            p = Path(raw)
            if p.exists():
                candidates.append(p)
        except OSError as e:
            log.debug("path check failed for %s: %s", raw, e)
    return candidates


# ============================================================================
# CWD -> project slug
# ============================================================================


def derive_slug_from_cwd(cwd: str | None) -> str | None:
    """
    Claude Code encodes the cwd as a folder under .claude/projects/.
    Historically that's the absolute path with separators replaced by `-`
    and a leading `-` (Claude Code's own convention).
    """
    if not cwd:
        return None
    # Normalize separators; drop drive colon to mirror Claude Code's slug scheme.
    norm = cwd.replace("\\", "/").replace(":", "")
    norm = re.sub(r"/+", "/", norm)
    slug = "-" + norm.strip("/").replace("/", "-")
    return slug


def find_project_dir(data_path: Path, cwd: str | None) -> Optional[Path]:
    slug = derive_slug_from_cwd(cwd)
    projects_root = data_path / "projects"
    if not projects_root.exists():
        return None
    if slug:
        direct = projects_root / slug
        if direct.exists():
            return direct
    # Fallback: any project folder that endswith the basename of cwd
    if cwd:
        base = os.path.basename(cwd.rstrip("/\\"))
        for candidate in projects_root.iterdir():
            if candidate.is_dir() and candidate.name.endswith(f"-{base}"):
                return candidate
    return None


def find_active_jsonl(cwd: str | None, data_paths: list[Path]) -> Optional[Path]:
    """Find the most-recently-touched JSONL for this cwd across all data paths."""
    candidates: list[Path] = []
    for dp in data_paths:
        project_dir = find_project_dir(dp, cwd)
        if project_dir is None:
            continue
        for jsonl in project_dir.rglob("*.jsonl"):
            try:
                candidates.append(jsonl)
            except OSError:
                continue
    if not candidates:
        return None
    try:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except OSError:
        return None


# ============================================================================
# Parsing
# ============================================================================


@dataclass
class JsonlSummary:
    path: Path
    size_bytes: int
    last_mtime: float
    messages: list[dict]
    last_role: Optional[str]
    last_stop_reason: Optional[str]
    last_message_text: Optional[str]
    tool_use_pending: bool
    model: Optional[str]
    tokens_in: int
    tokens_out: int
    session_id: Optional[str]
    started_at_ms: Optional[int]


def parse_jsonl_tail(path: Path, max_messages: int = 40) -> list[dict]:
    """
    Read the last N lines efficiently using a reverse seek. Returns parsed dicts
    in file order (oldest → newest within the slice).
    """
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            chunk = min(size, 256 * 1024)
            f.seek(max(0, size - chunk), os.SEEK_SET)
            blob = f.read()
    except OSError as e:
        log.debug("tail read failed %s: %s", path, e)
        return []

    lines = blob.splitlines()
    # Drop leading partial line if we didn't start at file begin
    if len(lines) > 1 and len(blob) >= 256 * 1024:
        lines = lines[1:]
    parsed: list[dict] = []
    for raw in lines[-max_messages:]:
        if not raw.strip():
            continue
        try:
            parsed.append(json.loads(raw.decode("utf-8", errors="replace")))
        except json.JSONDecodeError:
            continue
    return parsed


def summarize_jsonl(path: Path) -> JsonlSummary:
    """Extract status/token info from a JSONL. Returns sensible defaults on errors."""
    try:
        stat = path.stat()
    except OSError:
        return JsonlSummary(
            path=path, size_bytes=0, last_mtime=0,
            messages=[], last_role=None, last_stop_reason=None,
            last_message_text=None, tool_use_pending=False,
            model=None, tokens_in=0, tokens_out=0,
            session_id=None, started_at_ms=None,
        )

    messages = parse_jsonl_tail(path, max_messages=60)
    tokens_in = 0
    tokens_out = 0
    model: Optional[str] = None
    session_id: Optional[str] = None
    started_at_ms: Optional[int] = None
    last_role: Optional[str] = None
    last_stop_reason: Optional[str] = None
    last_text: Optional[str] = None
    tool_use_pending = False

    for m in messages:
        # Many claude-code JSONL variants exist; we tolerate them all.
        role = m.get("role") or m.get("type") or m.get("message", {}).get("role")
        msg = m.get("message") if isinstance(m.get("message"), dict) else m
        usage = (msg.get("usage") if isinstance(msg, dict) else None) or m.get("usage")
        if isinstance(usage, dict):
            tokens_in += int(usage.get("input_tokens") or 0)
            tokens_out += int(usage.get("output_tokens") or 0)
        if not model:
            model = msg.get("model") if isinstance(msg, dict) else None
        if not session_id:
            session_id = m.get("sessionId") or m.get("session_id") or m.get("uuid")
        if started_at_ms is None:
            ts = m.get("timestamp") or m.get("ts") or m.get("created_at")
            if isinstance(ts, (int, float)):
                started_at_ms = int(ts)

        if role:
            last_role = role
        stop = (msg.get("stop_reason") if isinstance(msg, dict) else None) or m.get("stop_reason")
        if stop:
            last_stop_reason = stop

        # Extract a readable last message
        content = msg.get("content") if isinstance(msg, dict) else None
        if content:
            last_text = _extract_text(content)
            if _has_pending_tool_use(content):
                tool_use_pending = True
            else:
                tool_use_pending = False

    return JsonlSummary(
        path=path,
        size_bytes=stat.st_size,
        last_mtime=stat.st_mtime,
        messages=messages,
        last_role=last_role,
        last_stop_reason=last_stop_reason,
        last_message_text=last_text,
        tool_use_pending=tool_use_pending,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        session_id=session_id,
        started_at_ms=started_at_ms,
    )


def _extract_text(content) -> Optional[str]:
    if isinstance(content, str):
        return content[:2000]
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                parts.append(str(block["text"]))
            elif block.get("type") == "tool_use":
                name = block.get("name") or "tool"
                parts.append(f"[tool_use: {name}]")
        if parts:
            return "\n".join(parts)[:2000]
    return None


def _has_pending_tool_use(content) -> bool:
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "tool_use"
            for b in content
        )
    return False


def read_full_jsonl(path: Path, max_bytes: int = 4 * 1024 * 1024) -> str:
    """Read up to `max_bytes` of the file for archiving."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size <= max_bytes:
                return f.read().decode("utf-8", errors="replace")
            # Keep head + tail for context
            head = f.read(max_bytes // 2)
            f.seek(-(max_bytes // 2), os.SEEK_END)
            tail = f.read()
            return (
                head.decode("utf-8", errors="replace")
                + "\n...[truncated]...\n"
                + tail.decode("utf-8", errors="replace")
            )
    except OSError as e:
        log.warning("read_full_jsonl failed %s: %s", path, e)
        return ""


def enumerate_all_jsonls(data_paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for dp in data_paths:
        projects = dp / "projects"
        if not projects.exists():
            continue
        try:
            for jsonl in projects.rglob("*.jsonl"):
                out.append(jsonl)
        except OSError as e:
            log.debug("enumerate failed at %s: %s", projects, e)
    return out
