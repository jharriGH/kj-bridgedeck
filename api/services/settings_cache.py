"""In-memory settings cache with hot-reload on update.

Loaded once on app startup. Every PATCH /settings/* call invalidates the
relevant slice. Reads are O(1) dict lookups under an asyncio lock.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from services.supabase_client import fetch_all, fetch_one

logger = logging.getLogger("bridgedeck.api.settings_cache")


class SettingsCache:
    _cache: dict[str, dict[str, Any]] = {}
    _lock = asyncio.Lock()
    _initialized = False

    @classmethod
    async def initialize(cls) -> None:
        try:
            rows = await fetch_all("settings")
            async with cls._lock:
                cls._cache.clear()
                for row in rows:
                    ns = row["namespace"]
                    cls._cache.setdefault(ns, {})[row["key"]] = row["value"]
                cls._initialized = True
            logger.info(
                "settings cache initialized: %d namespaces, %d keys",
                len(cls._cache),
                sum(len(v) for v in cls._cache.values()),
            )
        except Exception as e:
            logger.error("settings cache init failed: %s", e)

    @classmethod
    async def close(cls) -> None:
        async with cls._lock:
            cls._cache.clear()
            cls._initialized = False

    @classmethod
    async def get(cls, namespace: str, key: str, default: Any = None) -> Any:
        async with cls._lock:
            return cls._cache.get(namespace, {}).get(key, default)

    @classmethod
    async def get_namespace(cls, namespace: str) -> dict[str, Any]:
        async with cls._lock:
            return dict(cls._cache.get(namespace, {}))

    @classmethod
    async def all(cls) -> dict[str, dict[str, Any]]:
        async with cls._lock:
            return {ns: dict(kv) for ns, kv in cls._cache.items()}

    @classmethod
    async def invalidate(
        cls,
        namespace: Optional[str] = None,
        key: Optional[str] = None,
    ) -> None:
        if namespace and key:
            row = await fetch_one("settings", namespace=namespace, key=key)
            async with cls._lock:
                if row:
                    cls._cache.setdefault(namespace, {})[key] = row["value"]
                else:
                    cls._cache.get(namespace, {}).pop(key, None)
        elif namespace:
            rows = await fetch_all("settings", namespace=namespace)
            async with cls._lock:
                cls._cache[namespace] = {r["key"]: r["value"] for r in rows}
        else:
            await cls.initialize()
