"""Settings — admin CRUD with hot-reload cache."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import history_logger
from services.settings_cache import SettingsCache
from services.supabase_client import (
    fetch_all,
    fetch_one,
    insert,
    run_sync,
    table,
    update as sb_update,
)

router = APIRouter()


class SettingPatch(BaseModel):
    value: Any


@router.get("")
async def list_all() -> dict[str, dict]:
    return await SettingsCache.all()


@router.get("/{namespace}")
async def list_namespace(namespace: str) -> dict[str, Any]:
    ns = await SettingsCache.get_namespace(namespace)
    if not ns:
        raise HTTPException(404, f"namespace {namespace} not found")
    return ns


@router.get("/{namespace}/{key}")
async def get_setting(namespace: str, key: str) -> dict:
    row = await fetch_one("settings", namespace=namespace, key=key)
    if not row:
        raise HTTPException(404, f"setting {namespace}.{key} not found")
    return row


@router.patch("/{namespace}/{key}")
async def update_setting(namespace: str, key: str, body: SettingPatch) -> dict:
    existing = await fetch_one("settings", namespace=namespace, key=key)
    if not existing:
        raise HTTPException(404, f"setting {namespace}.{key} not found")

    old_value = existing["value"]
    new_value = body.value

    # Validate new value type matches old
    if old_value is not None and new_value is not None:
        if type(old_value) is not type(new_value):
            allowed_pairs = {(int, float), (float, int)}
            if (type(old_value), type(new_value)) not in allowed_pairs:
                raise HTTPException(
                    422,
                    f"value type mismatch: existing={type(old_value).__name__}, "
                    f"new={type(new_value).__name__}",
                )

    def _do():
        return (
            table("settings")
            .update({"value": new_value, "updated_by": "api"})
            .eq("namespace", namespace)
            .eq("key", key)
            .execute()
        )
    res = await run_sync(_do)
    rows = res.data or []
    updated = rows[0] if rows else {**existing, "value": new_value}

    await SettingsCache.invalidate(namespace, key)

    await history_logger.log(
        event_type="setting.changed",
        event_category="setting",
        actor="api",
        action="patch_setting",
        target=f"{namespace}.{key}",
        before_state={"value": old_value},
        after_state={"value": new_value},
    )

    return {
        "namespace": namespace,
        "key": key,
        "old_value": old_value,
        "new_value": new_value,
        "updated_at": updated.get("updated_at"),
    }


@router.post("/reset")
async def reset_namespace(namespace: str) -> dict:
    """Reset a namespace cache by re-reading from DB. Does not restore seeded
    defaults — that requires re-running schema.sql."""
    await SettingsCache.invalidate(namespace)
    ns = await SettingsCache.get_namespace(namespace)
    await history_logger.log(
        event_type="setting.namespace_reloaded",
        event_category="setting",
        actor="api",
        action="reset_namespace",
        target=namespace,
    )
    return {"namespace": namespace, "keys": list(ns.keys())}
