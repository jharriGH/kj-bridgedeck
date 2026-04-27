"""Proxy to the local watcher service on Jim's machine.

Only works when API is running on the same machine as watcher.
Render-hosted API cannot reach localhost:7171 — these routes return 503
with guidance when watcher is unreachable.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException

from config import settings

logger = logging.getLogger("bridgedeck.api.watcher")


class WatcherClient:
    def __init__(self) -> None:
        self.host = (settings.WATCHER_HOST or "").rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.host)

    async def health(self) -> str:
        if not self.configured:
            return "not_configured"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.host}/health")
                return "ok" if resp.status_code == 200 else "down"
        except Exception:
            return "down"

    async def call(self, method: str, path: str, **kwargs) -> Any:
        if not self.configured:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "watcher_unreachable",
                    "message": "WATCHER_HOST is not configured. The cloud-hosted "
                    "API cannot proxy session control. Run the local companion "
                    "API on the watcher machine.",
                },
            )
        url = f"{self.host}{path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp.json()
        except httpx.ConnectError as e:
            logger.warning("watcher connect failed: %s", e)
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "watcher_unreachable",
                    "message": f"Could not reach watcher at {self.host}. "
                    "Is the watcher running on the local machine?",
                },
            )
        except httpx.HTTPStatusError as e:
            logger.warning("watcher returned %d for %s", e.response.status_code, path)
            raise HTTPException(
                status_code=e.response.status_code,
                detail=e.response.text,
            )
