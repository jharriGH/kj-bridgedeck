"""History — query, search, export, timeline."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse, Response

from services.supabase_client import run_sync, table

router = APIRouter()


def _build_query(
    project: Optional[str] = None,
    category: Optional[str] = None,
    event_type: Optional[str] = None,
    from_ts: Optional[datetime] = None,
    to_ts: Optional[datetime] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    def _do():
        q = table("history_log").select("*")
        if project:
            q = q.eq("project_slug", project)
        if category:
            q = q.eq("event_category", category)
        if event_type:
            q = q.eq("event_type", event_type)
        if from_ts:
            q = q.gte("created_at", from_ts.isoformat())
        if to_ts:
            q = q.lte("created_at", to_ts.isoformat())
        if search:
            q = q.ilike("action", f"%{search}%")
        return q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return _do


@router.get("")
async def query_history(
    project: Optional[str] = None,
    category: Optional[str] = None,
    type: Optional[str] = None,
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    search: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    res = await run_sync(
        _build_query(project, category, type, from_, to, search, limit, offset)
    )
    return res.data or []


@router.get("/export")
async def export_history(
    format: str = Query("json", pattern="^(json|csv)$"),
    project: Optional[str] = None,
    category: Optional[str] = None,
    type: Optional[str] = None,
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    limit: int = Query(10000, ge=1, le=100000),
):
    res = await run_sync(
        _build_query(project, category, type, from_, to, None, limit, 0)
    )
    rows = res.data or []

    if format == "json":
        return Response(
            content=json.dumps(rows, default=str, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="history.json"'},
        )

    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for r in rows:
            writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v
                             for k, v in r.items()})
    return PlainTextResponse(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="history.csv"'},
    )


@router.get("/timeline")
async def activity_timeline(minutes: int = Query(60, ge=1, le=1440)) -> dict:
    """Hourly buckets for the last N minutes — Monitor tab bar chart."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    def _do():
        return (
            table("history_log")
            .select("created_at,event_category")
            .gte("created_at", cutoff.isoformat())
            .order("created_at", desc=False)
            .execute()
        )

    res = await run_sync(_do)
    rows = res.data or []

    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        ts = row["created_at"]
        bucket = ts[:16]
        cat = row["event_category"]
        buckets.setdefault(bucket, {}).setdefault(cat, 0)
        buckets[bucket][cat] += 1

    return {
        "minutes": minutes,
        "from": cutoff.isoformat(),
        "buckets": [{"timestamp": ts, "counts": counts} for ts, counts in sorted(buckets.items())],
    }


@router.get("/categories")
async def list_categories() -> dict:
    def _do():
        return table("history_log").select("event_category,event_type").limit(5000).execute()
    res = await run_sync(_do)
    rows = res.data or []
    out: dict[str, set[str]] = {}
    for row in rows:
        out.setdefault(row["event_category"], set()).add(row["event_type"])
    return {cat: sorted(types) for cat, types in out.items()}
