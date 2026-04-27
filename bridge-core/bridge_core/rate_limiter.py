"""Sliding-window rate trackers for outbound API calls.

The Anthropic org-level limit (50K input tokens / minute, observed live
2026-04-27) was the immediate driver. Same primitive supports OpenAI
Whisper or any other rolling-window cap.

Single-process tracking only. Render runs one worker today; if we go
multi-worker, swap the deque for Redis. The protocol stays the same.

Usage:
    tracker = anthropic_input_tokens_tracker()
    allowed, status, msg = tracker.can_consume(15_000)
    if not allowed:
        # log to rate_limit_blocks; either queue+retry or abort
        ...
    tracker.consume(15_000)   # only after the call succeeds
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from threading import Lock
from typing import Tuple

logger = logging.getLogger(__name__)


class SlidingWindowRateTracker:
    """Generic sliding-window tracker for any API rate limit."""

    def __init__(
        self, name: str, window_seconds: int, soft_limit: int, hard_limit: int
    ):
        self.name = name
        self.WINDOW_SECONDS = window_seconds
        self.SOFT_LIMIT = soft_limit
        self.HARD_LIMIT = hard_limit
        self._events: deque[tuple[float, int]] = deque()
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _purge_old(self) -> None:
        cutoff = time.time() - self.WINDOW_SECONDS
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def current_usage(self) -> int:
        with self._lock:
            self._purge_old()
            return sum(units for _, units in self._events)

    def can_consume(self, units: int) -> Tuple[bool, str, str]:
        """Decide whether to allow a request that would consume `units`.

        Returns ``(allowed, status, message)`` where status is one of:
          ``"ok"``    — well under both limits
          ``"warn"``  — over soft, under hard (still allowed)
          ``"block"`` — would exceed hard limit (not allowed)
        """
        with self._lock:
            self._purge_old()
            current = sum(u for _, u in self._events)
            if current + units > self.HARD_LIMIT:
                return (
                    False, "block",
                    f"{self.name}: {current}+{units} > {self.HARD_LIMIT} hard",
                )
            if current + units > self.SOFT_LIMIT:
                return (
                    True, "warn",
                    f"{self.name}: {current}+{units} > {self.SOFT_LIMIT} soft",
                )
            return True, "ok", f"{self.name}: {current}+{units} ok"

    def consume(self, units: int) -> None:
        with self._lock:
            self._events.append((time.time(), int(max(0, units))))

    def seconds_until_capacity(self, units: int) -> float:
        """Estimate seconds until `units` becomes consumable.

        Walks the window from oldest to newest and finds the moment when
        enough events have aged out to fit `units` under HARD_LIMIT."""
        with self._lock:
            self._purge_old()
            now = time.time()
            current = sum(u for _, u in self._events)
            if current + units <= self.HARD_LIMIT:
                return 0.0
            need = current + units - self.HARD_LIMIT
            freed = 0
            for ts, u in self._events:
                freed += u
                if freed >= need:
                    return max(0.0, ts + self.WINDOW_SECONDS - now)
            # shouldn't happen — units alone exceeds hard cap
            return float(self.WINDOW_SECONDS)

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "window_seconds": self.WINDOW_SECONDS,
            "soft_limit": self.SOFT_LIMIT,
            "hard_limit": self.HARD_LIMIT,
            "current_usage": self.current_usage(),
        }


# ---------------------------------------------------------------------------
# Per-provider singletons
# ---------------------------------------------------------------------------
#
# Anthropic org-level rate observed live 2026-04-27 was 50K input tokens / min.
# Soft = 80% of hard so the watcher can preemptively switch to Haiku before
# we actually hit the wall.

_ANTHROPIC_INPUT_TOKENS = SlidingWindowRateTracker(
    name="anthropic_input_tpm",
    window_seconds=60,
    soft_limit=40_000,
    hard_limit=50_000,
)

_OPENAI_WHISPER_REQUESTS = SlidingWindowRateTracker(
    name="openai_whisper_rpm",
    window_seconds=60,
    soft_limit=40,
    hard_limit=50,
)


def anthropic_input_tokens_tracker() -> SlidingWindowRateTracker:
    return _ANTHROPIC_INPUT_TOKENS


def whisper_requests_tracker() -> SlidingWindowRateTracker:
    return _OPENAI_WHISPER_REQUESTS


def all_trackers() -> list[SlidingWindowRateTracker]:
    return [_ANTHROPIC_INPUT_TOKENS, _OPENAI_WHISPER_REQUESTS]


# ---------------------------------------------------------------------------
# Wait-or-block helper
# ---------------------------------------------------------------------------


MAX_QUEUE_WAIT_SECONDS = 30


async def wait_for_capacity(
    tracker: SlidingWindowRateTracker,
    units: int,
    max_wait_seconds: int = MAX_QUEUE_WAIT_SECONDS,
) -> tuple[bool, float]:
    """Sleep up to `max_wait_seconds` for capacity to free.

    Returns ``(succeeded, waited_seconds)``. If the wait would exceed the
    limit we give up immediately so the caller can either fall back to a
    cheaper model or surface an error to the user.
    """
    waited = 0.0
    while True:
        eta = tracker.seconds_until_capacity(units)
        if eta <= 0:
            return True, waited
        if waited + eta > max_wait_seconds:
            return False, waited
        sleep_for = min(eta, max_wait_seconds - waited, 5.0)
        await asyncio.sleep(sleep_for)
        waited += sleep_for
