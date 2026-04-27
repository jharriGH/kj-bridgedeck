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
        return table("live_sessions").select("session_id,status,cost_usd").execute()

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

    live = (await run_sync(_do_live)).data or []
    today_rows = (await run_sync(_do_today)).data or []
    week_rows = (await run_sync(_do_week)).data or []

    return {
        "active_sessions": sum(1 for r in live if r["status"] != "ended"),
        "total_live_sessions": len(live),
        "today_sessions": len(today_rows),
        "today_spend_usd": round(sum(float(r.get("cost_total") or 0) for r in today_rows), 4),
        "today_live_spend_usd": round(sum(float(r.get("cost_usd") or 0) for r in live), 4),
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
