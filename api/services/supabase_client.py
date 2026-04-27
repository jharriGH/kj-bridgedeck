"""Supabase client singleton.

The supabase-py client is sync; we wrap it in a thin runner for async use.
The schema-qualified table name is `kjcodedeck.<table>`. The supabase python
client requires `schema='kjcodedeck'` on the postgrest call to switch schemas.
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from config import settings

logger = logging.getLogger("bridgedeck.api.supabase")

SCHEMA = "kjcodedeck"


@lru_cache
def get_supabase() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


def table(name: str):
    """Return a postgrest query builder pinned to the kjcodedeck schema."""
    return get_supabase().postgrest.schema(SCHEMA).from_(name)


async def run_sync(fn, *args, **kwargs) -> Any:
    """Execute a sync supabase call in a thread so we don't block the loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)


async def fetch_all(table_name: str, **filters) -> list[dict]:
    """Convenience: select * with simple eq filters."""
    def _do():
        q = table(table_name).select("*")
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.execute()
    res = await run_sync(_do)
    return res.data or []


async def fetch_one(table_name: str, **filters) -> dict | None:
    def _do():
        q = table(table_name).select("*")
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.limit(1).execute()
    res = await run_sync(_do)
    rows = res.data or []
    return rows[0] if rows else None


async def insert(table_name: str, payload: dict | list[dict]) -> list[dict]:
    res = await run_sync(lambda: table(table_name).insert(payload).execute())
    return res.data or []


async def update(table_name: str, patch: dict, **filters) -> list[dict]:
    def _do():
        q = table(table_name).update(patch)
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.execute()
    res = await run_sync(_do)
    return res.data or []


async def delete(table_name: str, **filters) -> list[dict]:
    def _do():
        q = table(table_name).delete()
        for k, v in filters.items():
            q = q.eq(k, v)
        return q.execute()
    res = await run_sync(_do)
    return res.data or []


async def ping() -> bool:
    try:
        await run_sync(lambda: table("settings").select("namespace").limit(1).execute())
        return True
    except Exception as e:
        logger.warning("supabase ping failed: %s", e)
        return False
