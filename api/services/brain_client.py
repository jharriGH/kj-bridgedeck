"""Thin httpx client for the Brain service."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from config import settings

logger = logging.getLogger("bridgedeck.api.brain")


class BrainClient:
    def __init__(self) -> None:
        self.base = settings.BRAIN_API_URL.rstrip("/")
        # Brain (verified live 2026-04-27 against jim-brain-production.up.railway.app
        # v1.3.2) requires `x-brain-key`. The legacy X-API-Key / Bearer headers
        # are kept for backwards-compat with older Brain builds — Brain ignores
        # unknown headers, so sending all three is harmless.
        self.headers = {
            "x-brain-key": settings.BRAIN_KEY,
            "X-API-Key": settings.BRAIN_KEY,
            "Authorization": f"Bearer {settings.BRAIN_KEY}",
        }

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base}{path}"
        async with httpx.AsyncClient(timeout=15.0, headers=self.headers) as client:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            if resp.headers.get("content-type", "").startswith("application/json"):
                return resp.json()
            return resp.text

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base}/health")
                return resp.status_code == 200
        except Exception as e:
            logger.warning("brain health check failed: %s", e)
            return False

    async def log(
        self,
        project_slug: str,
        content: str,
        tags: Optional[list[str]] = None,
        agent: str = "bridgedeck_api",
    ) -> dict:
        payload = {
            "project_slug": project_slug,
            "content": content,
            "tags": tags or [],
            "agent": agent,
        }
        return await self._request("POST", "/log", json=payload)

    async def context(self, slug: str, depth: str = "standard") -> dict:
        return await self._request(
            "GET", f"/codedeck/context/{slug}", params={"depth": depth}
        )

    async def projects(self) -> dict:
        """GET /projects — verified shape: {"projects":[...], "count":N}.

        Each project: {id, label, color, emoji, desc?, group?, status?,
        next_action?}. Includes a {"id":"all"} pseudo-project that callers
        must filter."""
        return await self._request("GET", "/projects")

    async def create_project(self, project: dict) -> dict:
        return await self._request("POST", "/codedeck/projects", json=project)

    async def handoff(self, payload: dict) -> dict:
        return await self._request("POST", "/codedeck/handoff", json=payload)
