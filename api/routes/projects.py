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
    """Pull project list from Brain /codedeck/projects and upsert locally."""
    try:
        brain_projects = await BrainClient().projects()
    except Exception as e:
        raise HTTPException(502, f"brain unreachable: {e}")

    now = datetime.now(timezone.utc).isoformat()
    synced = 0

    for bp in brain_projects:
        slug = bp.get("slug")
        if not slug:
            continue
        existing = await fetch_one("projects", slug=slug)
        payload = {
            "slug": slug,
            "display_name": bp.get("display_name") or bp.get("name") or slug,
            "emoji": bp.get("emoji"),
            "color": bp.get("color") or "#00E5FF",
            "repo_path": bp.get("repo_url") or bp.get("repo_path"),
            "description": bp.get("description"),
            "last_synced_from_brain": now,
        }
        if existing:
            await sb_update("projects", payload, slug=slug)
        else:
            await insert("projects", payload)
        synced += 1

    await history_logger.log(
        event_type="project.synced_from_brain",
        event_category="action",
        actor="api",
        action="sync_projects",
        details={"synced": synced},
    )
    return {"ok": True, "synced": synced}


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
