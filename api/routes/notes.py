"""Notes — CRUD with Brain sync per Brain Claude's approved architecture."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import history_logger
from services.brain_client import BrainClient
from services.supabase_client import (
    delete as sb_delete,
    fetch_all,
    fetch_one,
    insert,
    run_sync,
    table,
    update as sb_update,
)

logger = logging.getLogger("bridgedeck.api.notes")

router = APIRouter()


class NoteCreate(BaseModel):
    project_slug: str
    note_text: str
    session_id: Optional[str] = None
    tags: list[str] = []


class NotePatch(BaseModel):
    note_text: Optional[str] = None
    tags: Optional[list[str]] = None


@router.get("")
async def list_notes() -> list[dict]:
    def _do():
        return (
            table("session_notes")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
    res = await run_sync(_do)
    return res.data or []


@router.get("/project/{slug}")
async def project_notes(slug: str) -> list[dict]:
    return await fetch_all("session_notes", project_slug=slug)


@router.post("")
async def create_note(body: NoteCreate) -> dict:
    payload = body.model_dump()
    payload["brain_sync"] = "pending"
    rows = await insert("session_notes", payload)
    if not rows:
        raise HTTPException(500, "note insert returned no row")
    note = rows[0]

    brain_sync = "pending"
    try:
        tags = list(set(body.tags + ["codedeck_note", body.project_slug]))
        await BrainClient().log(
            project_slug=body.project_slug,
            content=body.note_text,
            tags=tags,
            agent="bridgedeck_api",
        )
        brain_sync = "sent"
    except Exception as e:
        logger.warning("brain log failed for note %s: %s", note["id"], e)
        brain_sync = "failed"

    if brain_sync != "pending":
        await sb_update("session_notes", {"brain_sync": brain_sync}, id=note["id"])
        note["brain_sync"] = brain_sync

    await history_logger.log(
        event_type="note.created",
        event_category="action",
        actor="api",
        action="create_note",
        project_slug=body.project_slug,
        session_id=body.session_id,
        target=note["id"],
        after_state={"brain_sync": brain_sync},
    )
    return note


@router.patch("/{note_id}")
async def update_note(note_id: str, body: NotePatch) -> dict:
    existing = await fetch_one("session_notes", id=note_id)
    if not existing:
        raise HTTPException(404, f"note {note_id} not found")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        return existing
    rows = await sb_update("session_notes", patch, id=note_id)
    note = rows[0] if rows else existing
    await history_logger.log(
        event_type="note.updated",
        event_category="action",
        actor="api",
        action="update_note",
        project_slug=existing["project_slug"],
        target=note_id,
        before_state={k: existing.get(k) for k in patch},
        after_state=patch,
    )
    return note


@router.delete("/{note_id}")
async def delete_note(note_id: str) -> dict:
    existing = await fetch_one("session_notes", id=note_id)
    if not existing:
        raise HTTPException(404, f"note {note_id} not found")
    await sb_delete("session_notes", id=note_id)
    await history_logger.log(
        event_type="note.deleted",
        event_category="action",
        actor="api",
        action="delete_note",
        project_slug=existing["project_slug"],
        target=note_id,
        before_state=existing,
    )
    return {"ok": True, "deleted": note_id}
