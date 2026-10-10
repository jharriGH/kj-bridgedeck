"""Stats — empire + project aggregates."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from services.supabase_client import fetch_one, run_sync, table

router = APIRouter()


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _week_start() -> datetime:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/empire")
async def empire_stats() -> dict:
    today = _today_start().isoformat()
    week = _week_start().isoformat()

    def _do_live():
        # Today's live activity: filter on last_activity instead of summing
        # lifetime costs of stale rows. STATS_EMPIRE_TODAY_FIX_V1
        return table("live_sessions").select(
            "session_id,status,cost_usd,last_activity"
        ).execute()

    def _do_today():
        return (
            table("session_archive")
            .select("session_id,cost_total")
            .gte("ended_at", today)
            .execute()
        )

    def _do_week():
        return (
            table("session_archive")
            .select("session_id,cost_total")
            .gte("ended_at", week)
            .execute()
        )

    def _do_cost_log_today():
        # cost_log is the empire-wide source of truth post-Phase-3.2 — every
        # KJE product (and cc_dispatch as of Phase A) POSTs here per call.
        return (
            table("cost_log")
            .select("id,cost_usd,session_id,source_system,created_at")
            .gte("created_at", today)
            .execute()
        )

    live = (await run_sync(_do_live)).data or []
    today_rows = (await run_sync(_do_today)).data or []
    week_rows = (await run_sync(_do_week)).data or []
    try:
        cost_log_today = (await run_sync(_do_cost_log_today)).data or []
    except Exception:
        cost_log_today = []

    # Only count live sessions whose last_activity is in the current day.
    live_today = [
        r for r in live
        if r.get("last_activity") and r["last_activity"] >= today
    ]
    # today_live_spend_usd: prefer authoritative cost_log sum, fall back to
    # live_sessions filtered by last_activity if cost_log is empty/missing.
    cost_log_total = round(
        sum(float(r.get("cost_usd") or 0) for r in cost_log_today), 4
    )
    live_today_total = round(
        sum(float(r.get("cost_usd") or 0) for r in live_today), 4
    )
    today_live_spend_usd = cost_log_total if cost_log_total > 0 else live_today_total

    # today_sessions: count of sessions that actually saw activity today,
    # combining archived (ended) sessions and currently-live sessions that
    # have today's activity. Distinct on session_id so a still-running
    # session isn't double-counted with its archive when it ends.
    today_session_ids: set[str] = set()
    today_session_ids.update(r["session_id"] for r in today_rows if r.get("session_id"))
    today_session_ids.update(r["session_id"] for r in live_today if r.get("session_id"))
    today_session_ids.update(
        r["session_id"] for r in cost_log_today if r.get("session_id")
    )

    return {
        "active_sessions": sum(1 for r in live if r["status"] != "ended"),
        "total_live_sessions": len(live),
        "today_sessions": len(today_session_ids),
        "today_spend_usd": round(sum(float(r.get("cost_total") or 0) for r in today_rows), 4),
        "today_live_spend_usd": today_live_spend_usd,
        "today_cost_log_usd": cost_log_total,
        "today_live_only_usd": live_today_total,
        "today_active_sessions": len(today_session_ids),
        "week_sessions": len(week_rows),
        "week_spend_usd": round(sum(float(r.get("cost_total") or 0) for r in week_rows), 4),
    }


@router.get("/project/{slug}")
async def project_stats(slug: str) -> dict:
    project = await fetch_one("projects", slug=slug)
    if not project:
        raise HTTPException(404, f"project {slug} not found")

    def _do_live():
        return (
            table("live_sessions")
            .select("session_id,status,cost_usd,tokens_in,tokens_out")
            .eq("project_slug", slug)
            .execute()
        )

    def _do_archive():
        return (
            table("session_archive")
            .select("session_id,cost_total,token_total,ended_at")
            .eq("project_slug", slug)
            .execute()
        )

    live = (await run_sync(_do_live)).data or []
    archive = (await run_sync(_do_archive)).data or []

    return {
        "slug": slug,
        "active_sessions": sum(1 for r in live if r["status"] != "ended"),
        "live_cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in live), 4),
        "live_tokens_in": sum(int(r.get("tokens_in") or 0) for r in live),
        "live_tokens_out": sum(int(r.get("tokens_out") or 0) for r in live),
        "archived_sessions": len(archive),
        "total_cost_usd": round(sum(float(r.get("cost_total") or 0) for r in archive), 4),
        "total_tokens": sum(int(r.get("token_total") or 0) for r in archive),
        "daily_budget_usd": float(project.get("daily_budget_usd") or 0),
        "weekly_budget_usd": float(project.get("weekly_budget_usd") or 0),
    }


@router.get("/cost/timeline")
async def cost_timeline(
    bucket: Literal["hour", "day"] = "day",
    days: int = Query(7, ge=1, le=90),
) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    def _do():
        return (
            table("session_archive")
            .select("ended_at,cost_total,project_slug")
            .gte("ended_at", cutoff)
            .execute()
        )

    rows = (await run_sync(_do)).data or []
    buckets: dict[str, float] = defaultdict(float)
    slice_len = 13 if bucket == "hour" else 10  # YYYY-MM-DDTHH or YYYY-MM-DD

    for row in rows:
        ts = row["ended_at"][:slice_len]
        buckets[ts] += float(row.get("cost_total") or 0)

    return {
        "bucket": bucket,
        "days": days,
        "points": [
            {"timestamp": ts, "cost_usd": round(v, 4)}
            for ts, v in sorted(buckets.items())
        ],
    }


@router.get("/activity/timeline")
async def activity_timeline(
    minutes: int = Query(60, ge=1, le=1440),
) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

    def _do():
        return (
            table("history_log")
            .select("created_at,event_category,project_slug")
            .gte("created_at", cutoff)
            .execute()
        )

    rows = (await run_sync(_do)).data or []
    buckets: dict[str, int] = defaultdict(int)
    for row in rows:
        ts = row["created_at"][:16]
        buckets[ts] += 1

    return {
        "minutes": minutes,
        "points": [
            {"timestamp": ts, "events": v}
            for ts, v in sorted(buckets.items())
        ],
    }
