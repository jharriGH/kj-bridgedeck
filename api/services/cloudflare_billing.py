"""Cloudflare hosting spend — best-effort estimate from accessible surfaces.

Cloudflare's account-level billing API (``/accounts/{id}/subscriptions``,
``/accounts/{id}/billing/profile``, ``/user/billing/profile``) requires a
billing-scoped API token. Most operational tokens — including the one
provisioned for KJE empire automation — only carry zone-edit scopes, so
those endpoints return HTTP 403 and we cannot enumerate paid account
subscriptions or Registrar / Workers / R2 line items.

This module reports what we CAN see (zone plan prices) and surfaces every
inaccessible billable surface as a structured ``gaps`` list so the UI can
warn loudly rather than silently under-report. ``monthly_total_usd`` is
explicitly labeled best-effort in the ``notes`` field.

Public surface:
    ``async def get_cloudflare_spend() -> dict``

Response shape:
    {
      "monthly_total_usd": float,
      "subscriptions": [{"name": str, "plan": str, "cost_usd": float}, ...],
      "fetched_at": ISO-8601 timestamp,
      "configured": bool,
      "notes": str,
      "gaps": [str, ...],
    }

Result is cached in-process for 1 hour — Cloudflare billing doesn't
change minute-to-minute and the underlying API is rate-limited.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger("bridgedeck.api.cloudflare_billing")

CF_API_BASE = "https://api.cloudflare.com/client/v4"
CACHE_TTL_SECONDS = 3600.0  # 1 hour

# Billable surfaces that require a billing-scoped API token. If a fetch
# 403s we list the surface here so the response advertises the gap rather
# than reporting $0 silently.
PROBED_SURFACES = [
    ("account_subscriptions", "/accounts/{account_id}/subscriptions"),
    ("registrar_domains",     "/accounts/{account_id}/registrar/domains"),
    ("workers_scripts",       "/accounts/{account_id}/workers/scripts"),
    ("r2_buckets",            "/accounts/{account_id}/r2/buckets"),
]

_cache: dict[str, Any] = {"value": None, "expires_at": 0.0}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _fetch_json(client: httpx.AsyncClient, path: str) -> tuple[int, Any]:
    try:
        resp = await client.get(f"{CF_API_BASE}{path}")
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, None
    except httpx.HTTPError as exc:
        logger.warning("cloudflare_billing: request to %s failed: %s", path, exc)
        return 0, None


async def _fetch_all_zones(client: httpx.AsyncClient, account_id: str) -> list[dict]:
    """Paginate through every zone owned by this account. Returns flat list."""
    zones: list[dict] = []
    page = 1
    while True:
        path = f"/zones?per_page=50&page={page}&account.id={account_id}"
        status, body = await _fetch_json(client, path)
        if status != 200 or not isinstance(body, dict) or not body.get("success"):
            break
        results = body.get("result") or []
        zones.extend(results)
        info = body.get("result_info") or {}
        total_pages = int(info.get("total_pages") or 0)
        if not results or page >= total_pages:
            break
        page += 1
    return zones


def _missing_config_response() -> dict:
    missing = [
        k for k in ("CF_API_TOKEN", "CF_ACCOUNT_ID")
        if not (os.environ.get(k) or "").strip()
    ]
    return {
        "monthly_total_usd": 0.0,
        "subscriptions": [],
        "fetched_at": _now_utc_iso(),
        "configured": False,
        "notes": (
            f"Not configured: missing {', '.join(missing)} on the API service "
            "environment. Set both env vars and redeploy to enable this tile."
        ),
        "gaps": [],
    }


async def get_cloudflare_spend() -> dict:
    """Best-effort monthly Cloudflare spend from zone plans + a probe of
    account-level billable surfaces. Cached 1h. Stable shape on every
    error path so the UI tile never crashes the Cost tab."""
    now = time.monotonic()
    cached = _cache.get("value")
    if cached is not None and now < _cache["expires_at"]:
        return cached

    token = (os.environ.get("CF_API_TOKEN") or "").strip()
    account_id = (os.environ.get("CF_ACCOUNT_ID") or "").strip()
    if not token or not account_id:
        logger.warning(
            "cloudflare_billing: CF_API_TOKEN or CF_ACCOUNT_ID not set — returning 'not configured'"
        )
        return _missing_config_response()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    subscriptions: list[dict] = []
    total = 0.0
    gaps: list[str] = []
    notes_lines: list[str] = []

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        # Token sanity.
        v_status, v_body = await _fetch_json(client, "/user/tokens/verify")
        if v_status != 200 or not (isinstance(v_body, dict) and v_body.get("success")):
            logger.warning("cloudflare_billing: token verify failed status=%s", v_status)
            return {
                "monthly_total_usd": 0.0,
                "subscriptions": [],
                "fetched_at": _now_utc_iso(),
                "configured": True,
                "notes": (
                    f"CF_API_TOKEN verify returned HTTP {v_status}. "
                    "Token may be revoked or scoped incorrectly."
                ),
                "gaps": [],
            }

        # Probe billable surfaces that require billing scope. Any 403 means
        # the line items behind that surface aren't summed in the total.
        for label, path_tmpl in PROBED_SURFACES:
            path = path_tmpl.format(account_id=account_id)
            status, _ = await _fetch_json(client, path)
            if status == 403:
                gaps.append(label)

        # Zone plans — the only billable surface we can read reliably.
        zones = await _fetch_all_zones(client, account_id)
        # Group identical plans into a single subscription row.
        by_plan: dict[str, dict] = {}
        for z in zones:
            plan = z.get("plan") or {}
            slug = plan.get("legacy_id") or plan.get("name") or "unknown"
            price = float(plan.get("price") or 0)
            bucket = by_plan.setdefault(slug, {
                "plan": slug,
                "plan_name": plan.get("name") or slug,
                "unit_price": price,
                "zones": 0,
            })
            bucket["zones"] += 1
            # If different zones somehow report different prices for the
            # same legacy_id, take the max so we don't undercount.
            if price > bucket["unit_price"]:
                bucket["unit_price"] = price

        for slug, b in by_plan.items():
            cost = b["unit_price"] * b["zones"]
            total += cost
            subscriptions.append({
                "name": f"Zones × {b['zones']} ({b['plan_name']})",
                "plan": slug,
                "cost_usd": round(cost, 2),
            })

    # Surface the gap loudly in notes — best-effort total only covers what
    # we can actually read.
    notes_lines.append("Best-effort estimate from zone plans only.")
    if gaps:
        notes_lines.append(
            "Inaccessible billable surfaces (token lacks billing scope): "
            + ", ".join(gaps)
            + ". Real Cloudflare bill may be higher; check the dashboard."
        )
    else:
        notes_lines.append("All probed account surfaces returned OK.")

    result = {
        "monthly_total_usd": round(total, 2),
        "subscriptions": sorted(subscriptions, key=lambda s: s["cost_usd"], reverse=True),
        "fetched_at": _now_utc_iso(),
        "configured": True,
        "notes": " ".join(notes_lines),
        "gaps": gaps,
    }
    _cache["value"] = result
    _cache["expires_at"] = now + CACHE_TTL_SECONDS
    return result
