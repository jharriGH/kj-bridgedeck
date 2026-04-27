"""Handoffs — read-only views of session_handoffs."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from services.supabase_client import fetch_one, run_sync, table

router = APIRouter()


@router.get("")
async def list_handoffs(
    project: Optional[str] = None,
    status: Optional[str] = None,
    confidence_min: Optional[float] = Query(None, ge=0, le=1),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    def _do():
        q = table("session_handoffs").select("*")
        if project:
            q = q.eq("project_slug", project)
        if status:
            q = q.eq("status", status)
        if confidence_min is not None:
            q = q.gte("confidence", confidence_min)
        return q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    res = await run_sync(_do)
    return res.data or []


@router.get("/{handoff_id}")
async def get_handoff(handoff_id: str) -> dict:
    row = await fetch_one("session_handoffs", id=handoff_id)
    if not row:
        raise HTTPException(404, f"handoff {handoff_id} not found")
    return row


@router.get("/project/{slug}")
async def project_handoffs(
    slug: str,
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    def _do():
        return (
            table("session_handoffs")
            .select("*")
            .eq("project_slug", slug)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
    res = await run_sync(_do)
    return res.data or []
