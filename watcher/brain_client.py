"""
Brain API client.

Brain v1.4.0 contract:
  POST /codedeck/handoff   (x-brain-key header)
  GET  /codedeck/context/{slug}?depth=standard

We retry on network/5xx errors with exponential backoff (60s, 120s, done).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from shared.contracts import BrainHandoffResponse, SessionHandoff
from watcher.config import get_config

log = logging.getLogger(__name__)

# NOTIFY_STORM_FIX_V1 — the summarizer-failure path used to fire one SMS per
# session end with zero dedup. A burst of degraded sessions (e.g. 8 zombie
# watchers flushing their trackers on restart) turned that into a text-bomb
# aimed at Jim. Collapse repeats of the same notify topic into silence for
# this long; the first one still gets through.
_NOTIFY_COOLDOWN_SECONDS = 900  # 15 min
_last_notify_at: dict[str, float] = {}


class BrainClient:
    def __init__(self, timeout: float = 30.0) -> None:
        cfg = get_config()
        self.url = cfg.brain_api_url.rstrip("/")
        self.key = cfg.brain_key
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-brain-key": self.key, "Content-Type": "application/json"}

    async def send_handoff(
        self, handoff: SessionHandoff, *, max_attempts: int = 3
    ) -> BrainHandoffResponse:
        payload = handoff.model_dump()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            last_err: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    resp = await client.post(
                        f"{self.url}/codedeck/handoff",
                        headers=self._headers,
                        json=payload,
                    )
                    if resp.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"Brain returned {resp.status_code}", request=resp.request, response=resp
                        )
                    resp.raise_for_status()
                    return BrainHandoffResponse(**resp.json())
                except (httpx.HTTPError, ValueError) as e:
                    last_err = e
                    if attempt == max_attempts - 1:
                        break
                    backoff = 60 * (attempt + 1)
                    log.warning(
                        "Brain handoff attempt %d failed: %s — retrying in %ds",
                        attempt + 1, e, backoff,
                    )
                    await asyncio.sleep(backoff)
            assert last_err is not None
            raise last_err

    async def fetch_context(self, project_slug: str, depth: str = "standard") -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.url}/codedeck/context/{project_slug}",
                headers=self._headers,
                params={"depth": depth},
            )
            resp.raise_for_status()
            return resp.json()

    async def notify(
        self,
        message: str,
        severity: str = "warn",
        channel: str = "both",
        *,
        dedup_key: str | None = None,
    ) -> dict[str, Any]:
        """POST /notify — best-effort. A failed notify must never raise past
        the caller; the degraded-run path that fires this still needs the
        session-end flow to finish (archive, blob mirror, cleanup).

        NOTIFY_STORM_FIX_V1: when `dedup_key` is given, at most one send per
        `_NOTIFY_COOLDOWN_SECONDS` window — repeats within the window log
        once and return quietly instead of texting Jim again. On failure,
        one bounded retry, then quiet (never a per-session SMS loop)."""
        if dedup_key is not None:
            now = time.monotonic()
            last = _last_notify_at.get(dedup_key)
            if last is not None and (now - last) < _NOTIFY_COOLDOWN_SECONDS:
                log.info(
                    "brain_notify suppressed (dedup_key=%s, %.0fs into cooldown)",
                    dedup_key, now - last,
                )
                return {"ok": False, "suppressed": True, "reason": "cooldown"}
            _last_notify_at[dedup_key] = now

        payload = {"severity": severity, "message": message[:500], "channel": channel}
        last_err: Exception | None = None
        for attempt in range(2):  # one try + one bounded retry, then quiet
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.url}/notify",
                        headers=self._headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                    return resp.json()
            except httpx.HTTPError as e:
                last_err = e
                if attempt == 0:
                    log.warning("brain_notify attempt 1 failed: %s — retrying once", e)
                    await asyncio.sleep(5)
        log.warning("brain_notify failed after retry, giving up quietly: %s", last_err)
        return {"ok": False, "error": str(last_err)}
