"""Gather Brain + Supabase context scoped to the classified intent.

Keep queries tight. Each intent has one preferred bundle of sources so we
don't blow token budget pulling everything on every turn.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from shared.contracts import BridgeSources

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15.0
SESSION_HANDOFFS_TABLE = "kjcodedeck.session_handoffs"
LIVE_SESSIONS_TABLE = "kjcodedeck.live_sessions"
SESSION_ARCHIVE_TABLE = "kjcodedeck.session_archive"
COST_LOG_TABLE = "kjcodedeck.cost_log"


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
        sources.memories = await self._memory_search(client, message, top_k=5)

    async def _gather_session_history(
        self,
        client: httpx.AsyncClient,
        sources: BridgeSources,
        project_slug: str | None,
        message: str,
        time_range_days: int | None,
    ) -> None:
        # Default window: 1 day for "history" queries unless caller said otherwise.
        days = time_range_days or 1
        await self._gather_multi_source_activity(
            client, sources, project_slug, message, days
        )

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
        # Multi-source activity aggregator. Default 7-day window for empire
        # summaries; a project_slug=None means "the whole empire".
        days = time_range_days or 7
        await self._gather_multi_source_activity(
            client, sources, project_slug, message, days
        )

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

    # ------------------------------------------------------------------
    # Multi-source aggregation — used by session_history and empire_summary.
    # Pulls handoffs + cost_log + Brain cards + Brain memories + git log so
    # the assistant has real signal even when handoffs are empty (which is
    # the common case until the watcher is installed as a service).
    # ------------------------------------------------------------------

    async def _gather_multi_source_activity(
        self,
        client: httpx.AsyncClient,
        sources: BridgeSources,
        project_slug: str | None,
        message: str,
        days: int,
    ) -> None:
        since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        # Run the five independent reads in parallel; fall back to empty on any
        # individual failure so one slow source can't stall the whole turn.
        handoffs_t = self._recent_handoffs(project_slug, since)
        cost_t     = self._recent_cost_log(project_slug, since)
        cards_t    = self._recent_cards(client, since)
        memories_t = self._memory_search(client, message or "recent activity", top_k=5)
        git_t      = self._recent_git_commits(since)
        handoffs, cost_rows, cards, memories, git_rows = await asyncio.gather(
            handoffs_t, cost_t, cards_t, memories_t, git_t,
            return_exceptions=False,
        )

        # Existing typed slots
        sources.handoffs = (handoffs or [])[:10]
        sources.memories = (memories or [])[:5]
        sources.cards    = (cards or [])[:5]

        # The cost/git aggregates don't have first-class slots in
        # BridgeSources, so we attach them to projects with a typed wrapper
        # the prompt knows how to render.
        activity_summary: dict[str, Any] = {
            "_activity_summary": True,
            "window_days": days,
            "since": since.isoformat(),
            "counts": {
                "handoffs": len(sources.handoffs),
                "cost_log_bridge": sum(1 for r in (cost_rows or []) if r.get("source_system") == "bridge"),
                "cost_log_cc_session": sum(1 for r in (cost_rows or []) if r.get("source_system") == "cc_session"),
                "cost_log_other": sum(1 for r in (cost_rows or []) if r.get("source_system") not in ("bridge","cc_session")),
                "brain_cards": len(sources.cards),
                "brain_memories": len(sources.memories),
                "git_commits": len(git_rows or []),
            },
            "cost_log_recent": (cost_rows or [])[:25],
            "git_recent": (git_rows or [])[:30],
        }
        # Prepend so the model sees the activity summary first; preserve any
        # earlier projects load (e.g. empire_summary's slim project list).
        sources.projects = [activity_summary, *sources.projects]

    # ------------------------------------------------------------------
    # Source readers
    # ------------------------------------------------------------------

    async def _recent_handoffs(
        self, project_slug: str | None, since: datetime
    ) -> list[dict]:
        kw: dict[str, Any] = {
            "order": ("created_at", True),
            "limit": 10,
            "gte": {"created_at": since.isoformat()},
        }
        if project_slug:
            kw["eq"] = {"project_slug": project_slug}
        rows = await self._supabase_select(SESSION_HANDOFFS_TABLE, **kw) or []
        return [
            {
                "session_id": r.get("session_id"),
                "project_slug": r.get("project_slug"),
                "summary": (r.get("summary") or "")[:600],
                "next_action": (r.get("next_action") or "")[:200],
                "confidence": r.get("confidence"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]

    async def _recent_cost_log(
        self, project_slug: str | None, since: datetime
    ) -> list[dict]:
        kw: dict[str, Any] = {
            "order": ("created_at", True),
            "limit": 50,
            "gte": {"created_at": since.isoformat()},
        }
        if project_slug:
            kw["eq"] = {"project_slug": project_slug}
        rows = await self._supabase_select(COST_LOG_TABLE, **kw) or []
        # Drop noisy fields; keep what helps the model summarize activity.
        return [
            {
                "source_system": r.get("source_system"),
                "project_slug": r.get("project_slug"),
                "session_id": r.get("session_id"),
                "intent": r.get("intent"),
                "model": r.get("model"),
                "cost_usd": r.get("cost_usd"),
                "tokens_in": r.get("tokens_in"),
                "tokens_out": r.get("tokens_out"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]

    async def _recent_cards(
        self, client: httpx.AsyncClient, since: datetime
    ) -> list[dict]:
        """GET /cards. Brain v1.3.2 doesn't honor query filters — see
        BridgeDeck enhancement card 1777340856363 — so we filter client-side
        on `saved_at`."""
        resp = await self._cached_get(client, "/cards", ttl_seconds=120)
        cards = resp.get("cards") if isinstance(resp, dict) else (resp or [])
        if not isinstance(cards, list):
            return []
        cutoff = since.isoformat()
        recent = [
            {
                "id": c.get("id"),
                "title": c.get("title"),
                "project": c.get("project"),
                "content_excerpt": (c.get("content") or "")[:600],
                "saved_at": c.get("saved_at"),
            }
            for c in cards
            if (c.get("saved_at") or "") >= cutoff
        ]
        # Newest first.
        recent.sort(key=lambda c: c.get("saved_at") or "", reverse=True)
        return recent

    async def _memory_search(
        self, client: httpx.AsyncClient, query: str, top_k: int = 5
    ) -> list[dict]:
        """Brain /memory/search returns {query, results, count}. The legacy
        code expected a bare list, which silently dropped every result —
        fixed here to extract `results`."""
        resp = await self._safe_get(
            client, "/memory/search", params={"q": query, "top_k": top_k},
        )
        if isinstance(resp, dict):
            items = resp.get("results") or []
        elif isinstance(resp, list):
            items = resp
        else:
            return []
        return [
            {
                "id": m.get("id"),
                "memory": (m.get("memory") or "")[:600],
                "score": m.get("score"),
                "created_at": m.get("created_at"),
                "metadata": m.get("metadata"),
            }
            for m in items[:top_k]
        ]

    async def _recent_git_commits(self, since: datetime) -> list[dict]:
        """Best-effort git log of the cwd (the API repo). Walks up from the
        current working directory looking for a .git folder; returns [] if
        git isn't on PATH or the cwd isn't a checkout (e.g. running in a
        bare container)."""
        if not shutil.which("git"):
            return []
        # Walk up looking for .git
        cwd = Path.cwd().resolve()
        repo_root: Path | None = None
        for cand in (cwd, *cwd.parents):
            if (cand / ".git").exists():
                repo_root = cand
                break
        if repo_root is None:
            return []

        def _run() -> list[dict]:
            try:
                proc = subprocess.run(
                    [
                        "git", "log",
                        f"--since={since.isoformat()}",
                        "--pretty=format:%H|%an|%ad|%s",
                        "--date=iso",
                        "-n", "30",
                    ],
                    cwd=str(repo_root),
                    capture_output=True, text=True, timeout=5,
                )
                if proc.returncode != 0:
                    return []
                out: list[dict] = []
                for line in proc.stdout.splitlines():
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        out.append({
                            "sha": parts[0][:10],
                            "author": parts[1],
                            "date": parts[2],
                            "subject": parts[3][:200],
                        })
                return out
            except Exception as exc:
                logger.debug("git log failed: %s", exc)
                return []

        return await asyncio.to_thread(_run)

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
