"""Gather Brain + Supabase context scoped to the classified intent.

Keep queries tight. Each intent has one preferred bundle of sources so we
don't blow token budget pulling everything on every turn.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx

from shared.contracts import BridgeSources

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15.0
SESSION_HANDOFFS_TABLE = "kjcodedeck.session_handoffs"
LIVE_SESSIONS_TABLE = "kjcodedeck.live_sessions"
SESSION_ARCHIVE_TABLE = "kjcodedeck.session_archive"


class _BrainCache:
    """In-memory TTL cache for Brain GETs that we hit on every Bridge turn.

    Brain `/projects` and `/context` are slow + heavy and rarely change
    inside a 60-second window. Cache them so back-to-back Bridge turns
    don't re-fetch identical payloads."""

    _cache: dict[str, tuple[Any, float]] = {}

    @classmethod
    async def get_or_fetch(
        cls,
        key: str,
        fetcher: Callable[[], Awaitable[Any]],
        ttl_seconds: int = 60,
    ) -> Any:
        now = time.time()
        hit = cls._cache.get(key)
        if hit is not None:
            value, expires_at = hit
            if now < expires_at:
                return value
        value = await fetcher()
        cls._cache[key] = (value, now + ttl_seconds)
        return value

    @classmethod
    def invalidate(cls, key: str | None = None) -> None:
        if key is None:
            cls._cache.clear()
        else:
            cls._cache.pop(key, None)


class ContextGatherer:
    """Pulls exactly the right Brain/Supabase context for a given intent."""

    def __init__(self, brain_url: str, brain_key: str, supabase_client: Any):
        self.brain_url = brain_url.rstrip("/")
        self.brain_key = brain_key
        self.supabase = supabase_client
        self._headers = {"x-brain-key": brain_key}

    async def gather(
        self,
        intent: str,
        project_slug: str | None,
        message: str,
        time_range_days: int | None = None,
    ) -> BridgeSources:
        sources = BridgeSources()
        handler_name = self._HANDLERS.get(intent, "_gather_general")
        handler = getattr(self, handler_name)
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            await handler(client, sources, project_slug, message, time_range_days)
        return sources

    # ------------------------------------------------------------------
    # Per-intent handlers
    # ------------------------------------------------------------------

    async def _gather_status(
        self,
        client: httpx.AsyncClient,
        sources: BridgeSources,
        project_slug: str | None,
        message: str,
        time_range_days: int | None,
    ) -> None:
        if not project_slug:
            await self._gather_general(client, sources, project_slug, message, time_range_days)
            return
        ctx = await self._safe_get(client, f"/codedeck/context/{project_slug}?depth=standard")
        cards = await self._safe_get(client, f"/cards?project={project_slug}&limit=3")
        if ctx is not None:
            sources.projects = [ctx]
        if isinstance(cards, list):
            sources.cards = cards

    async def _gather_next_action(
        self,
        client: httpx.AsyncClient,
        sources: BridgeSources,
        project_slug: str | None,
        message: str,
        time_range_days: int | None,
    ) -> None:
        all_projects = await self._cached_get(client, "/projects")
        if isinstance(all_projects, dict):
            all_projects = all_projects.get("projects") or []
        if isinstance(all_projects, list):
            sources.projects = [
                p for p in all_projects
                if p.get("status") == "in_progress" and p.get("id") != "all"
            ]

    async def _gather_fact_recall(
        self,
        client: httpx.AsyncClient,
        sources: BridgeSources,
        project_slug: str | None,
        message: str,
        time_range_days: int | None,
    ) -> None:
        memories = await self._safe_get(
            client,
            "/memory/search",
            params={"q": message, "top_k": 5},
        )
        if isinstance(memories, list):
            sources.memories = memories

    async def _gather_session_history(
        self,
        client: httpx.AsyncClient,
        sources: BridgeSources,
        project_slug: str | None,
        message: str,
        time_range_days: int | None,
    ) -> None:
        if project_slug:
            rows = await self._supabase_select(
                SESSION_HANDOFFS_TABLE,
                order=("created_at", True),
                limit=5,
                eq={"project_slug": project_slug},
            )
            sources.handoffs = rows or []
        memories = await self._safe_get(
            client,
            "/memory/search",
            params={"q": message, "top_k": 3},
        )
        if isinstance(memories, list):
            sources.memories = memories

    async def _gather_empire_summary(
        self,
        client: httpx.AsyncClient,
        sources: BridgeSources,
        project_slug: str | None,
        message: str,
        time_range_days: int | None,
    ) -> None:
        # GUARDRAIL 3: empire_summary uses lightweight /projects (slug + label
        # + status) + a scoped handoffs query. Never /context — that endpoint
        # returns full memory bundles for every project and easily blows the
        # 200K input-token cap on a multi-project empire.
        projects = await self._cached_get(client, "/projects")
        if isinstance(projects, dict):
            projects = projects.get("projects") or []
        if isinstance(projects, list):
            slim = [
                {
                    "slug": p.get("id"),
                    "label": p.get("label"),
                    "status": p.get("status"),
                    "next_action": p.get("next_action"),
                    "group": p.get("group"),
                }
                for p in projects
                if p.get("id") and p.get("id") != "all"
            ]
            sources.projects = slim
        days = time_range_days or 7
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = await self._supabase_select(
            SESSION_HANDOFFS_TABLE,
            order=("created_at", True),
            limit=20,
            gte={"created_at": since},
        )
        sources.handoffs = rows or []

    async def _gather_cost_query(
        self,
        client: httpx.AsyncClient,
        sources: BridgeSources,
        project_slug: str | None,
        message: str,
        time_range_days: int | None,
    ) -> None:
        days = time_range_days or 7
        aggregate = await self._aggregate_costs(days)
        sources.projects = [{"cost_aggregate": aggregate, "time_range_days": days}]

    async def _gather_launch_session(
        self,
        client: httpx.AsyncClient,
        sources: BridgeSources,
        project_slug: str | None,
        message: str,
        time_range_days: int | None,
    ) -> None:
        projects = await self._cached_get(client, "/projects")
        if isinstance(projects, dict):
            projects = projects.get("projects") or []
        if isinstance(projects, list):
            sources.projects = [p for p in projects if p.get("id") != "all"]

    async def _gather_save_memory(
        self,
        client: httpx.AsyncClient,
        sources: BridgeSources,
        project_slug: str | None,
        message: str,
        time_range_days: int | None,
    ) -> None:
        # No reads needed — the assistant emits a save_memory directive.
        return None

    async def _gather_general(
        self,
        client: httpx.AsyncClient,
        sources: BridgeSources,
        project_slug: str | None,
        message: str,
        time_range_days: int | None,
    ) -> None:
        ctx = await self._cached_get(client, "/context")
        if ctx is not None:
            sources.projects = [ctx]

    # Mapping intent string → handler method name. Defined after class body.
    _HANDLERS: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _cached_get(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        ttl_seconds: int = 60,
    ) -> Any:
        """`_safe_get` but with a 60-second in-memory cache. Use for high-
        traffic, slow-moving GETs (e.g. /projects, /context)."""
        cache_key = f"GET {path} {sorted((params or {}).items())}"
        return await _BrainCache.get_or_fetch(
            cache_key,
            lambda: self._safe_get(client, path, params=params),
            ttl_seconds=ttl_seconds,
        )

    async def _safe_get(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.brain_url}{path}"
        try:
            r = await client.get(url, headers=self._headers, params=params)
        except httpx.HTTPError as exc:
            logger.warning("Brain GET %s failed: %s", path, exc)
            return None
        if r.status_code != 200:
            logger.info("Brain GET %s returned %s", path, r.status_code)
            return None
        try:
            return r.json()
        except ValueError:
            return None

    async def _supabase_select(
        self,
        table: str,
        *,
        order: tuple[str, bool] | None = None,
        limit: int | None = None,
        eq: dict[str, Any] | None = None,
        gte: dict[str, Any] | None = None,
    ) -> list[dict] | None:
        """Thin wrapper around supabase-py for the handful of reads we need.

        `supabase-py` v2 is sync under the hood; we call it directly and
        tolerate either sync or async builder methods (tests inject mocks)."""
        try:
            q = self.supabase.table(table).select("*")
            for key, value in (eq or {}).items():
                q = q.eq(key, value)
            for key, value in (gte or {}).items():
                q = q.gte(key, value)
            if order:
                column, desc = order
                q = q.order(column, desc=desc)
            if limit is not None:
                q = q.limit(limit)
            result = q.execute()
            # Some fakes return an awaitable
            if hasattr(result, "__await__"):
                result = await result
            return getattr(result, "data", None)
        except Exception as exc:
            logger.warning("Supabase select %s failed: %s", table, exc)
            return None

    async def _aggregate_costs(self, days: int) -> dict[str, Any]:
        """Sum cost_usd across live_sessions + session_archive for last N days."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        totals: dict[str, float] = {}
        live = await self._supabase_select(
            LIVE_SESSIONS_TABLE,
            gte={"started_at": since},
        )
        archive = await self._supabase_select(
            SESSION_ARCHIVE_TABLE,
            gte={"started_at": since},
        )
        for row in (live or []) + (archive or []):
            slug = row.get("project_slug") or "unknown"
            totals[slug] = totals.get(slug, 0.0) + float(row.get("cost_usd") or 0)
        return {
            "total_usd": sum(totals.values()),
            "by_project": totals,
            "since": since,
        }


# Bind handler names after class body.
ContextGatherer._HANDLERS = {
    "status_query": "_gather_status",
    "next_action": "_gather_next_action",
    "fact_recall": "_gather_fact_recall",
    "session_history": "_gather_session_history",
    "empire_summary": "_gather_empire_summary",
    "cost_query": "_gather_cost_query",
    "launch_session": "_gather_launch_session",
    "save_memory": "_gather_save_memory",
    "general": "_gather_general",
}
