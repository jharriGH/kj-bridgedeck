"""Auto-approve rules CRUD."""
from __future__ import annotations

import fnmatch
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import history_logger
from services.supabase_client import (
    delete as sb_delete,
    fetch_all,
    fetch_one,
    insert,
    run_sync,
    table,
    update as sb_update,
)
from shared.contracts import AutoApproveRule

router = APIRouter()


class TestRequest(BaseModel):
    sample: str


@router.get("")
async def list_rules() -> list[dict]:
    def _do():
        return table("auto_approve_rules").select("*").order("created_at", desc=True).execute()
    res = await run_sync(_do)
    return res.data or []


@router.get("/project/{slug}")
async def project_rules(slug: str) -> list[dict]:
    return await fetch_all("auto_approve_rules", project_slug=slug)


@router.post("")
async def create_rule(rule: AutoApproveRule) -> dict:
    payload = rule.model_dump(exclude={"id", "fire_count", "last_fired"})
    rows = await insert("auto_approve_rules", payload)
    if not rows:
        raise HTTPException(500, "rule insert returned no row")
    new_rule = rows[0]
    await history_logger.log(
        event_type="auto_approve.rule_created",
        event_category="auto_approve",
        actor="api",
        action="create_rule",
        project_slug=rule.project_slug,
        target=new_rule["id"],
        after_state=payload,
    )
    return new_rule


@router.patch("/{rule_id}")
async def update_rule(rule_id: str, patch: dict) -> dict:
    existing = await fetch_one("auto_approve_rules", id=rule_id)
    if not existing:
        raise HTTPException(404, f"rule {rule_id} not found")
    rows = await sb_update("auto_approve_rules", patch, id=rule_id)
    updated = rows[0] if rows else existing
    await history_logger.log(
        event_type="auto_approve.rule_updated",
        event_category="auto_approve",
        actor="api",
        action="update_rule",
        project_slug=existing["project_slug"],
        target=rule_id,
        before_state={k: existing.get(k) for k in patch},
        after_state=patch,
    )
    return updated


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str) -> dict:
    existing = await fetch_one("auto_approve_rules", id=rule_id)
    if not existing:
        raise HTTPException(404, f"rule {rule_id} not found")
    await sb_delete("auto_approve_rules", id=rule_id)
    await history_logger.log(
        event_type="auto_approve.rule_deleted",
        event_category="auto_approve",
        actor="api",
        action="delete_rule",
        project_slug=existing["project_slug"],
        target=rule_id,
        before_state=existing,
    )
    return {"ok": True, "deleted": rule_id}


@router.post("/{rule_id}/test")
async def test_rule(rule_id: str, body: TestRequest) -> dict:
    rule = await fetch_one("auto_approve_rules", id=rule_id)
    if not rule:
        raise HTTPException(404, f"rule {rule_id} not found")

    pattern = rule["pattern"]
    matched = False
    error = None
    try:
        if rule["pattern_type"] == "regex":
            matched = bool(re.search(pattern, body.sample))
        elif rule["pattern_type"] == "glob":
            matched = fnmatch.fnmatch(body.sample, pattern)
        else:  # exact
            matched = body.sample == pattern
    except re.error as e:
        error = f"invalid regex: {e}"

    return {
        "rule_id": rule_id,
        "pattern": pattern,
        "pattern_type": rule["pattern_type"],
        "rule_type": rule["rule_type"],
        "sample": body.sample,
        "matched": matched,
        "would_fire": matched and rule["enabled"],
        "error": error,
    }
