"""Cost intelligence — read endpoints + cap CRUD.

Backed by `kjcodedeck.cost_log` (every billable call) and
`kjcodedeck.cost_caps` (empire/project/per-turn ceilings). Both tables ship
in `supabase/migrations/20260427_cost_intel.sql`. If the migration hasn't
been applied yet, every endpoint here returns an empty/zeroed payload
instead of 500'ing — the UI then renders zeros until the user runs the SQL.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import history_logger
from services.supabase_client import run_sync, table

logger = logging.getLogger("bridgedeck.api.cost")

router = APIRouter()

COST_LOG = "cost_log"
COST_CAPS = "cost_caps"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _safe_select_costs(*, since: datetime, project_slug: Optional[str] = None) -> list[dict]:
    """Pull cost_log rows for an aggregation window. Returns [] on missing
    table (migration not applied) so callers don't need to special-case it."""
    def _do():
        q = (
            table(COST_LOG)
            .select("*")
            .gte("created_at", since.isoformat())
            .order("created_at", desc=False)
        )
        if project_slug:
            q = q.eq("project_slug", project_slug)
        return q.execute()

    try:
        res = await run_sync(_do)
        return res.data or []
    except Exception as exc:
        logger.warning("cost_log select failed (migration applied?): %s", exc)
        return []


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# GET /cost/summary
# ---------------------------------------------------------------------------


@router.get("/summary")
async def summary() -> dict:
    now = datetime.now(timezone.utc)
    today = _start_of_day(now)
    week = now - timedelta(days=7)
    month = now - timedelta(days=30)

    rows_month = await _safe_select_costs(since=month)

    def _sum(rows: list[dict], gte: datetime) -> float:
        return float(
            sum(
                float(r.get("cost_usd") or 0)
                for r in rows
                if r.get("created_at") and r["created_at"] >= gte.isoformat()
            )
        )

    today_total = _sum(rows_month, today)
    week_total = _sum(rows_month, week)
    month_total = _sum(rows_month, month)

    by_project: dict[str, float] = defaultdict(float)
    by_session: dict[str, float] = defaultdict(float)
    for r in rows_month:
        slug = r.get("project_slug") or "—"
        by_project[slug] += float(r.get("cost_usd") or 0)
        sid = r.get("session_id")
        if sid:
            by_session[sid] += float(r.get("cost_usd") or 0)

    top_projects = sorted(
        ({"project_slug": k, "total_usd": round(v, 4)} for k, v in by_project.items()),
        key=lambda x: x["total_usd"], reverse=True,
    )[:10]
    top_sessions = sorted(
        ({"session_id": k, "total_usd": round(v, 4)} for k, v in by_session.items()),
        key=lambda x: x["total_usd"], reverse=True,
    )[:10]

    return {
        "today": round(today_total, 4),
        "week": round(week_total, 4),
        "month": round(month_total, 4),
        "top_projects": top_projects,
        "top_sessions": top_sessions,
    }


# ---------------------------------------------------------------------------
# GET /cost/timeline?days=30
# ---------------------------------------------------------------------------


@router.get("/timeline")
async def timeline(days: int = 30) -> dict:
    days = max(1, min(days, 90))
    since = _start_of_day(datetime.now(timezone.utc) - timedelta(days=days - 1))
    rows = await _safe_select_costs(since=since)

    buckets: dict[str, dict[str, float]] = {}
    for r in rows:
        ts = r.get("created_at") or ""
        date = ts[:10] if len(ts) >= 10 else "unknown"
        bucket = buckets.setdefault(date, {"total": 0.0})
        cost = float(r.get("cost_usd") or 0)
        bucket["total"] += cost
        src = r.get("source_system") or "other"
        bucket[src] = bucket.get(src, 0.0) + cost

    # Fill missing days with zeros so the heatmap renders without gaps.
    out: list[dict] = []
    for i in range(days):
        d = (since + timedelta(days=i)).date().isoformat()
        b = buckets.get(d, {"total": 0.0})
        b = {k: round(v, 4) for k, v in b.items()}
        out.append({"date": d, **b})
    return {"timeline": out, "days": days}


# ---------------------------------------------------------------------------
# GET /cost/by-project?days=7
# ---------------------------------------------------------------------------


@router.get("/by-project")
async def by_project(days: int = 7) -> dict:
    days = max(1, min(days, 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await _safe_select_costs(since=since)
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"total": 0.0})
    for r in rows:
        slug = r.get("project_slug") or "—"
        cost = float(r.get("cost_usd") or 0)
        bucket = totals[slug]
        bucket["total"] += cost
        bucket[r.get("source_system") or "other"] = (
            bucket.get(r.get("source_system") or "other", 0.0) + cost
        )
    out = sorted(
        ({"project_slug": k, **{kk: round(vv, 4) for kk, vv in v.items()}}
         for k, v in totals.items()),
        key=lambda x: x["total"], reverse=True,
    )
    return {"projects": out, "days": days}


# ---------------------------------------------------------------------------
# GET /cost/by-source?days=7
# ---------------------------------------------------------------------------


@router.get("/by-source")
async def by_source(days: int = 7) -> dict:
    days = max(1, min(days, 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await _safe_select_costs(since=since)
    totals: dict[str, float] = defaultdict(float)
    for r in rows:
        totals[r.get("source_system") or "other"] += float(r.get("cost_usd") or 0)
    return {
        "sources": {k: round(v, 4) for k, v in totals.items()},
        "days": days,
    }


# ---------------------------------------------------------------------------
# GET /cost/live
# ---------------------------------------------------------------------------


@router.get("/live")
async def live() -> dict:
    now = datetime.now(timezone.utc)
    today = _start_of_day(now)
    today_rows = await _safe_select_costs(since=today)
    today_total = float(sum(float(r.get("cost_usd") or 0) for r in today_rows))

    # Rough burn-rate from active live_sessions.
    burn_rate = 0.0
    try:
        def _live_sessions():
            return (
                table("live_sessions")
                .select("cost_usd,started_at,status")
                .neq("status", "ended")
                .execute()
            )
        live_res = await run_sync(_live_sessions)
        live_rows = live_res.data or []
        burn_rate = float(sum(float(r.get("cost_usd") or 0) for r in live_rows))
    except Exception as exc:
        logger.debug("burn-rate calc failed: %s", exc)

    return {
        "today": round(today_total, 4),
        "current_bridge_turn": 0.0,  # filled by client during a streaming turn
        "active_sessions_burn_rate": round(burn_rate, 4),
        "as_of": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /cost/caps   PATCH /cost/caps/{scope}
# ---------------------------------------------------------------------------


@router.get("/caps")
async def list_caps() -> dict:
    try:
        res = await run_sync(lambda: table(COST_CAPS).select("*").execute())
        return {"caps": res.data or []}
    except Exception as exc:
        logger.warning("cost_caps select failed: %s", exc)
        return {"caps": []}


class CapPatch(BaseModel):
    cap_usd: Optional[float] = None
    behavior: Optional[str] = None
    enabled: Optional[bool] = None


@router.patch("/caps/{scope}")
async def patch_cap(scope: str, body: CapPatch) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(400, "no fields to update")
    if "behavior" in patch and patch["behavior"] not in ("warn", "haiku_force", "hard_stop"):
        raise HTTPException(400, "behavior must be warn|haiku_force|hard_stop")
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()

    def _do():
        return (
            table(COST_CAPS).upsert({"scope": scope, **patch}, on_conflict="scope").execute()
        )

    try:
        res = await run_sync(_do)
    except Exception as exc:
        logger.warning("cost_caps upsert failed: %s", exc)
        raise HTTPException(500, f"cost_caps upsert failed: {exc}")

    await history_logger.log(
        event_type="setting.cost_cap_updated",
        event_category="setting",
        actor="api",
        action=f"upsert cap {scope}",
        target=scope,
        after_state=patch,
    )
    rows = res.data or []
    return rows[0] if rows else {"scope": scope, **patch}
