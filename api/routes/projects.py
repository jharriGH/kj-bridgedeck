"""Projects — sync from Brain + local CRUD."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import history_logger
from services.brain_client import BrainClient
from services.supabase_client import (
    fetch_all,
    fetch_one,
    insert,
    run_sync,
    table,
    update as sb_update,
)
from shared.contracts import Project

router = APIRouter()


class ProjectPatch(BaseModel):
    display_name: Optional[str] = None
    emoji: Optional[str] = None
    color: Optional[str] = None
    repo_path: Optional[str] = None
    description: Optional[str] = None
    daily_budget_usd: Optional[float] = None
    weekly_budget_usd: Optional[float] = None
    budget_behavior: Optional[str] = None
    auto_approve_enabled: Optional[bool] = None


@router.get("")
async def list_projects() -> list[dict]:
    projects = await fetch_all("projects")

    def _agg(slug: str):
        live = (
            table("live_sessions")
            .select("session_id,cost_usd,status")
            .eq("project_slug", slug)
            .neq("status", "ended")
            .execute()
        )
        archive = (
            table("session_archive")
            .select("session_id,cost_total")
            .eq("project_slug", slug)
            .execute()
        )
        return live, archive

    out = []
    for p in projects:
        try:
            live, archive = await run_sync(_agg, p["slug"])
            live_rows = live.data or []
            archive_rows = archive.data or []
            p["active_sessions"] = len(live_rows)
            p["archived_sessions"] = len(archive_rows)
            p["live_cost_usd"] = sum(float(r.get("cost_usd") or 0) for r in live_rows)
            p["total_cost_usd"] = sum(float(r.get("cost_total") or 0) for r in archive_rows)
        except Exception:
            p["active_sessions"] = 0
            p["archived_sessions"] = 0
            p["live_cost_usd"] = 0.0
            p["total_cost_usd"] = 0.0
        out.append(p)
    return out


@router.get("/{slug}")
async def get_project(slug: str) -> dict:
    project = await fetch_one("projects", slug=slug)
    if not project:
        raise HTTPException(404, f"project {slug} not found")

    project["sessions"] = await fetch_all("live_sessions", project_slug=slug)
    project["notes"] = await fetch_all("session_notes", project_slug=slug)

    def _do_handoffs():
        return (
            table("session_handoffs")
            .select("*")
            .eq("project_slug", slug)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
    handoffs_res = await run_sync(_do_handoffs)
    project["handoffs"] = handoffs_res.data or []
    return project


@router.post("/sync")
async def sync_from_brain() -> dict:
    """Pull project list from Brain /projects and upsert locally.

    Brain v1.3.2 shape (verified 2026-04-27):
        {"projects": [{"id","label","color","emoji","desc"?,"group"?,
                       "status"?,"next_action"?}, ...], "count": N}
    The first entry {"id":"all"} is a UI placeholder — skipped here.

    Field mapping: id→slug, label→display_name, desc→description.
    emoji + color land in their dedicated columns. group/status/next_action
    go into the optional `brain_extras` JSONB column added by
    `supabase/migrations/20260427_brain_extras.sql`. If that column doesn't
    exist yet, sync transparently retries without it — basic fields still
    land, just without the extras blob."""
    try:
        resp = await BrainClient().projects()
    except Exception as e:
        raise HTTPException(502, f"brain unreachable: {e}")

    brain_projects = resp.get("projects", []) if isinstance(resp, dict) else (resp or [])
    now = datetime.now(timezone.utc).isoformat()
    synced = 0
    skipped: list[dict] = []
    synced_slugs: list[str] = []

    for bp in brain_projects:
        if bp.get("id") == "all":
            continue
        slug = bp.get("id")
        if not slug:
            continue

        extras = {
            k: bp[k] for k in ("group", "status", "next_action") if bp.get(k) is not None
        }

        payload = {
            "slug": slug,
            "display_name": bp.get("label") or slug,
            "emoji": bp.get("emoji"),
            "color": bp.get("color") or "#00E5FF",
            "description": bp.get("desc"),
            "last_synced_from_brain": now,
        }
        if extras:
            payload["brain_extras"] = extras
        payload = {k: v for k, v in payload.items() if v is not None}
        payload["slug"] = slug

        try:
            await _upsert_with_extras_fallback(slug, payload)
            synced += 1
            synced_slugs.append(slug)
        except Exception as e:  # pragma: no cover — surface and continue
            skipped.append({"slug": slug, "error": str(e)[:200]})

    await history_logger.log(
        event_type="project.synced_from_brain",
        event_category="action",
        actor="api",
        action="sync_projects",
        details={"synced": synced, "projects": synced_slugs, "skipped": skipped},
    )
    return {"synced": synced, "projects": synced_slugs, "skipped": skipped}


async def _upsert_with_extras_fallback(slug: str, payload: dict) -> None:
    """Upsert a row; if Postgres rejects `brain_extras` (column missing in
    schema), drop it and retry once."""
    existing = await fetch_one("projects", slug=slug)
    try:
        if existing:
            await sb_update("projects", payload, slug=slug)
        else:
            await insert("projects", payload)
    except Exception as e:
        msg = str(e).lower()
        if "brain_extras" not in payload or "brain_extras" not in msg:
            raise
        retry = {k: v for k, v in payload.items() if k != "brain_extras"}
        if existing:
            await sb_update("projects", retry, slug=slug)
        else:
            await insert("projects", retry)


@router.post("")
async def create_project(project: Project) -> dict:
    existing = await fetch_one("projects", slug=project.slug)
    if existing:
        raise HTTPException(409, f"project {project.slug} already exists")

    payload = project.model_dump(exclude={"last_synced_from_brain"})
    rows = await insert("projects", payload)
    if not rows:
        raise HTTPException(500, "project insert returned no row")

    try:
        await BrainClient().create_project({
            "slug": project.slug,
            "display_name": project.display_name,
            "emoji": project.emoji,
            "color": project.color,
            "repo_url": project.repo_path,
            "description": project.description,
        })
    except Exception:
        # Brain may already have it — non-fatal
        pass

    await history_logger.log(
        event_type="project.created",
        event_category="action",
        actor="api",
        action="create_project",
        project_slug=project.slug,
        after_state=payload,
    )
    return rows[0]


@router.patch("/{slug}")
async def update_project(slug: str, body: ProjectPatch) -> dict:
    existing = await fetch_one("projects", slug=slug)
    if not existing:
        raise HTTPException(404, f"project {slug} not found")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        return existing
    rows = await sb_update("projects", patch, slug=slug)
    updated = rows[0] if rows else existing
    await history_logger.log(
        event_type="project.updated",
        event_category="action",
        actor="api",
        action="update_project",
        project_slug=slug,
        before_state={k: existing.get(k) for k in patch},
        after_state=patch,
    )
    return updated
