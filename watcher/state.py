"""
In-process shared state between the polling loop and the local HTTP API.

The API is read-mostly and occasionally issues commands (send_message,
approve, etc.). It needs to ask the poller "what sessions do you know about?"
without hitting Supabase. This module is that lookup.

Thread-safety: we use a simple lock. The poller runs in the asyncio loop;
the FastAPI handlers run on Uvicorn worker threads via the default executor.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Optional


class WatcherState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self.last_poll: Optional[datetime] = None
        self.started_at: datetime = datetime.now(timezone.utc)
        self.poll_error: Optional[str] = None

    def upsert(self, session_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._sessions[session_id] = data

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def get(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            sess = self._sessions.get(session_id)
            return dict(sess) if sess else None

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(s) for s in self._sessions.values()]

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def mark_poll(self) -> None:
        self.last_poll = datetime.now(timezone.utc)
        self.poll_error = None

    def mark_poll_error(self, err: str) -> None:
        self.poll_error = err


_state: Optional[WatcherState] = None


def get_state() -> WatcherState:
    global _state
    if _state is None:
        _state = WatcherState()
    return _state
