"""Render hosting spend — static plan-rate estimate.

The Render API doesn't expose live invoice data on standard plans, so this
module sums the *configured* plan rate for every service in the account.
Rates are verified against render.com pricing snapshots and cross-checked
against external sources; see the comment above ``PLAN_RATES`` below.

Public surface:
    ``async def get_render_spend() -> dict``

Response shape:
    {
      "total_monthly_estimated_usd": float,
      "service_count": int,
      "services": [
        {"name": str, "type": str, "plan": str, "monthly_usd": float, "unknown": bool},
        ...
      ],
      "fetched_at": ISO-8601 timestamp,
      "notes": "Static plan-rate estimate. For invoiced amounts see Render dashboard."
    }

Result is cached in-process for 60 seconds so repeated UI polls don't hammer
the Render API.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger("bridgedeck.api.render_billing")

RENDER_API_BASE = "https://api.render.com/v1"
CACHE_TTL_SECONDS = 60.0

# Rates verified 2026-05-07 against render.com/blog (April 2026 update).
# Cross-checked vs: kuberns, joinsecret, servercompass, encore.dev.
# pro_plus and pro_max marked None because cross-referenced sources disagree
# on the middle tiers; current account uses zero services on those plans.
# When a future service lands on one of them, get_render_spend() will flag
# it with ``unknown: true`` so we re-verify the rate before silently
# zero-counting (same lesson as the kje-cost-logger fix).
PLAN_RATES: dict[str, Optional[float]] = {
    "free": 0.0,
    "starter": 7.0,
    "standard": 25.0,
    "pro": 85.0,
    "pro_plus": None,
    "pro_max": None,
    "pro_ultra": 450.0,
}

# Service types whose Render service objects don't carry a per-instance ``plan``
# field (or whose plan field is non-billable). Static sites are always $0 on
# Render — bandwidth is billed at the workspace level, not the service level.
ZERO_COST_TYPES = {"static_site"}

_cache: dict[str, Any] = {"value": None, "expires_at": 0.0}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_for(svc: dict) -> tuple[str, str]:
    """Return (plan_slug, service_type) for a Render service object.

    The /v1/services payload wraps each entry in {"cursor": ..., "service": {...}}.
    The plan slug for web services and cron jobs lives at
    ``service.serviceDetails.plan``. Static sites have no ``plan`` field
    (only ``buildPlan``), which is handled by ZERO_COST_TYPES.
    """
    details = svc.get("serviceDetails") or {}
    plan = details.get("plan") or ""
    svc_type = svc.get("type") or "unknown"
    return plan, svc_type


def _rate_for(plan: str, svc_type: str) -> tuple[float, bool]:
    """Return (monthly_usd, unknown_flag) for a (plan, type) combination."""
    if svc_type in ZERO_COST_TYPES:
        return 0.0, False
    rate = PLAN_RATES.get(plan)
    if rate is None:
        logger.warning(
            "render_billing: unknown plan %r for type %r — flagging as unknown",
            plan, svc_type,
        )
        return 0.0, True
    return rate, False


async def _fetch_all_services(api_key: str) -> list[dict]:
    """Paginate /v1/services until exhausted. Returns flat list of service
    objects (with the {cursor, service} envelope unwrapped)."""
    out: list[dict] = []
    cursor: Optional[str] = None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        while True:
            params: dict[str, str] = {}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(f"{RENDER_API_BASE}/services", params=params or None)
            resp.raise_for_status()
            page = resp.json() or []
            if not isinstance(page, list) or not page:
                break
            for entry in page:
                svc = entry.get("service") if isinstance(entry, dict) else None
                if svc:
                    out.append(svc)
            # Render returns at most ~20 per page by default; if we got fewer
            # than we'd expect, we're done. Otherwise advance by the last
            # entry's cursor.
            last_cursor = page[-1].get("cursor") if isinstance(page[-1], dict) else None
            if not last_cursor or last_cursor == cursor:
                break
            cursor = last_cursor
            if len(page) < 20:
                break
    return out


async def get_render_spend() -> dict:
    """Total monthly Render spend estimate using static plan rates.

    Cached in-process for 60s. Returns a stable shape even on API failure
    (empty services list + zero total) so the UI tile keeps rendering and
    a re-fetch will succeed once Render's API recovers.
    """
    now = time.monotonic()
    cached = _cache.get("value")
    if cached is not None and now < _cache["expires_at"]:
        return cached

    api_key = (os.environ.get("RENDER_API_KEY") or "").strip()
    if not api_key:
        logger.warning("render_billing: RENDER_API_KEY not set in environment")
        return {
            "total_monthly_estimated_usd": 0.0,
            "service_count": 0,
            "services": [],
            "fetched_at": _now_utc_iso(),
            "notes": "RENDER_API_KEY not configured on this service.",
        }

    try:
        services_raw = await _fetch_all_services(api_key)
    except httpx.HTTPError as exc:
        logger.warning("render_billing: API call failed: %s", exc)
        return {
            "total_monthly_estimated_usd": 0.0,
            "service_count": 0,
            "services": [],
            "fetched_at": _now_utc_iso(),
            "notes": f"Render API call failed: {exc}",
        }

    services: list[dict] = []
    total = 0.0
    for svc in services_raw:
        plan, svc_type = _plan_for(svc)
        monthly, unknown = _rate_for(plan, svc_type)
        total += monthly
        services.append({
            "name": svc.get("name") or svc.get("slug") or "?",
            "type": svc_type,
            "plan": plan or ("—" if svc_type in ZERO_COST_TYPES else "unknown"),
            "monthly_usd": round(monthly, 2),
            "unknown": unknown,
        })

    services.sort(key=lambda s: s["monthly_usd"], reverse=True)
    result = {
        "total_monthly_estimated_usd": round(total, 2),
        "service_count": len(services),
        "services": services,
        "fetched_at": _now_utc_iso(),
        "notes": "Static plan-rate estimate. For invoiced amounts see Render dashboard.",
    }
    _cache["value"] = result
    _cache["expires_at"] = now + CACHE_TTL_SECONDS
    return result
