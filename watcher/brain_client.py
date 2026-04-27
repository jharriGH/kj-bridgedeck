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
from typing import Any

import httpx

from shared.contracts import BrainHandoffResponse, SessionHandoff
from watcher.config import get_config

log = logging.getLogger(__name__)


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
