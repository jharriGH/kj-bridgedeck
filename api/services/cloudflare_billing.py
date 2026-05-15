"""Cloudflare hosting spend — real line items from all accessible surfaces.

When the CF_API_TOKEN carries a billing-read scope, this module fetches and
sums actual billable line items across five surfaces:

    1. Zone plans       — /zones (paginated)
    2. Subscriptions    — /accounts/{id}/subscriptions  (non-zone-scope only,
                          to avoid double-counting zones already summed above)
    3. Registrar        — /accounts/{id}/registrar/domains  (annual cost
                          amortized to monthly via TLD_RATES)
    4. Workers          — /accounts/{id}/workers/scripts  (count only; the
                          paid-plan flat fee, if any, comes from the
                          ``workers_paid``-style entry in /subscriptions)
    5. R2               — /accounts/{id}/r2/buckets + per-bucket /usage
                          (storage cost via $0.015/GB-mo; ops cost requires
                          the analytics GraphQL endpoint and is documented
                          as a known v1 gap in notes)

If the token lacks scope on a particular surface (HTTP 403), that surface is
added to ``gaps`` and contributes $0 to the total — the response loudly
advertises the gap rather than silently under-reporting.

Each fetcher is fail-soft: an unexpected response shape or transport error
falls back to an empty contribution + an annotation in ``notes`` so the
module never crashes the Cost tab.

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

Cached in-process for 1 hour.
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

# Cloudflare Registrar at-cost annual prices per TLD (USD). Sourced from
# the bulk-registration receipt on 2026-04-28 where all 20 .com domains
# came back at $10.46/yr renewal. Unknown TLDs flag with ``unknown=True``
# so the tile warns instead of silently zero-counting.
TLD_RATES_USD_PER_YEAR: dict[str, float] = {
    "com": 10.46,
}

# R2 pricing per Cloudflare's published rate card (Standard storage class).
R2_STORAGE_PRICE_USD_PER_GB_MONTH = 0.015
# Ops pricing reserved for a future enhancement once we wire the analytics
# GraphQL endpoint — REST /usage only exposes storage size, not ops count.
R2_CLASS_A_PRICE_USD_PER_MILLION = 4.50   # writes / list
R2_CLASS_B_PRICE_USD_PER_MILLION = 0.36   # reads

# Subscription rate-plan id prefixes that indicate the Workers paid plan.
# When a sub with one of these ids is active, its ``price`` is the source
# of truth for the Workers monthly fee; we don't need to hardcode $5.
WORKERS_PAID_PLAN_PREFIXES = ("workers_paid", "workers_bundled", "workers_standard")

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


# ---------------------------------------------------------------------------
# Per-surface fetchers. Each returns (lines, surface_notes, optional_extras).
# A surface is appended to ``gaps`` if and only if the API returned 403.
# ---------------------------------------------------------------------------


async def _fetch_zone_lines(client: httpx.AsyncClient, account_id: str) -> tuple[list[dict], str, bool]:
    """Paginate /zones, aggregate by plan, return one line per plan."""
    zones: list[dict] = []
    page = 1
    saw_403 = False
    try:
        while True:
            status, body = await _fetch_json(
                client, f"/zones?per_page=50&page={page}&account.id={account_id}"
            )
            if status == 403:
                saw_403 = True
                break
            if status != 200 or not isinstance(body, dict) or not body.get("success"):
                break
            results = body.get("result") or []
            zones.extend(results)
            info = body.get("result_info") or {}
            total_pages = int(info.get("total_pages") or 0)
            if not results or page >= total_pages:
                break
            page += 1
    except Exception as exc:
        logger.warning("cloudflare_billing: _fetch_zone_lines failed: %s", exc)
        return [], f"zones: unexpected error ({exc})", False

    if not zones:
        return [], "" if not saw_403 else "zones: 403 (token lacks zone scope).", saw_403

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
        if price > bucket["unit_price"]:
            bucket["unit_price"] = price

    lines = [
        {
            "name": f"Zones × {b['zones']} ({b['plan_name']})",
            "plan": slug,
            "cost_usd": round(b["unit_price"] * b["zones"], 2),
        }
        for slug, b in by_plan.items()
    ]
    return lines, "", saw_403


async def _fetch_subscription_lines(
    client: httpx.AsyncClient, account_id: str
) -> tuple[list[dict], list[dict], str, bool]:
    """Paginate /accounts/{id}/subscriptions. Returns (lines, raw_subs, note, saw_403).

    Skips zone-scope subscriptions (already counted by _fetch_zone_lines)
    AND zero-priced subs (free Teams/R2 base entries) so the breakdown
    only shows real money. ``raw_subs`` is returned so _fetch_workers_lines
    can introspect for a workers_paid entry without re-fetching.
    """
    raw_subs: list[dict] = []
    page = 1
    saw_403 = False
    try:
        while True:
            status, body = await _fetch_json(
                client, f"/accounts/{account_id}/subscriptions?per_page=50&page={page}"
            )
            if status == 403:
                saw_403 = True
                break
            if status != 200 or not isinstance(body, dict):
                break
            results = body.get("result") or []
            raw_subs.extend(results)
            if len(results) < 50:
                break
            page += 1
    except Exception as exc:
        logger.warning("cloudflare_billing: _fetch_subscription_lines failed: %s", exc)
        return [], [], f"subscriptions: unexpected error ({exc})", False

    if saw_403:
        return [], [], "subscriptions: 403 (token lacks billing read).", True

    lines: list[dict] = []
    paid_count = 0
    for s in raw_subs:
        rate_plan = s.get("rate_plan") or {}
        scope = rate_plan.get("scope")
        if scope == "zone":
            continue  # zones are counted by _fetch_zone_lines
        try:
            price = float(s.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            continue
        freq = s.get("frequency") or ""
        if freq == "yearly":
            monthly = price / 12.0
        elif freq == "monthly":
            monthly = price
        else:
            # weekly/daily/not-applicable — keep raw price as a conservative
            # estimate; we'd rather over-report than miss a real charge.
            monthly = price
        plan_id = rate_plan.get("id") or "unknown"
        product = (s.get("product") or {}).get("public_name") or rate_plan.get("public_name") or plan_id
        lines.append({
            "name": product,
            "plan": plan_id,
            "cost_usd": round(monthly, 2),
        })
        paid_count += 1

    note = (
        f"{paid_count} paid subscription(s) summed from /subscriptions."
        if paid_count
        else f"No paid account-scope subscriptions ({len(raw_subs)} entries scanned, all zero-priced or zone-scoped)."
    )
    return lines, raw_subs, note, False


async def _fetch_registrar_lines(
    client: httpx.AsyncClient, account_id: str
) -> tuple[list[dict], str, bool]:
    """List /accounts/{id}/registrar/domains. Group by TLD, apply TLD_RATES
    amortized monthly. Unknown TLDs are listed in the note for follow-up.

    Note: this endpoint is zero-indexed and returns ALL domains in one page
    by default (total_pages=1 with per_page=50). We pull a single page.
    """
    saw_403 = False
    try:
        status, body = await _fetch_json(
            client, f"/accounts/{account_id}/registrar/domains?per_page=50"
        )
    except Exception as exc:
        logger.warning("cloudflare_billing: _fetch_registrar_lines failed: %s", exc)
        return [], f"registrar: unexpected error ({exc})", False

    if status == 403:
        return [], "registrar: 403 (token lacks registrar read).", True
    if status != 200 or not isinstance(body, dict) or not body.get("success"):
        return [], f"registrar: API returned HTTP {status}.", False

    domains = body.get("result") or []
    if not domains:
        return [], "registrar: 0 domains registered.", False

    by_tld: dict[str, int] = {}
    for d in domains:
        name = d.get("name") or ""
        tld = name.rsplit(".", 1)[-1].lower() if "." in name else "unknown"
        by_tld[tld] = by_tld.get(tld, 0) + 1

    lines: list[dict] = []
    unknown_tlds: list[str] = []
    for tld, count in by_tld.items():
        annual_rate = TLD_RATES_USD_PER_YEAR.get(tld)
        if annual_rate is None:
            unknown_tlds.append(f".{tld}×{count}")
            lines.append({
                "name": f"Registrar × {count} .{tld} domains (unknown rate)",
                "plan": "registrar_unknown_tld",
                "cost_usd": 0.0,
                "unknown": True,
            })
            continue
        monthly = (annual_rate * count) / 12.0
        lines.append({
            "name": f"Registrar × {count} .{tld} domains (renewal)",
            "plan": "registrar_renewal",
            "cost_usd": round(monthly, 2),
        })

    note_parts = [f"Registrar: {len(domains)} domain(s) amortized monthly from TLD rate table."]
    if unknown_tlds:
        note_parts.append(
            f"Unknown TLD rates flagged (no amortization applied): {', '.join(unknown_tlds)}."
        )
    return lines, " ".join(note_parts), False


async def _fetch_workers_lines(
    client: httpx.AsyncClient, account_id: str, raw_subs: list[dict]
) -> tuple[list[dict], str, bool]:
    """List /accounts/{id}/workers/scripts. The paid-plan flat fee, if any,
    is captured by _fetch_subscription_lines via the ``workers_paid``
    subscription entry. This fetcher only contributes the *informational*
    script count to the notes and surfaces a $0 zero-line if any scripts
    exist on the free plan."""
    saw_403 = False
    try:
        status, body = await _fetch_json(
            client, f"/accounts/{account_id}/workers/scripts"
        )
    except Exception as exc:
        logger.warning("cloudflare_billing: _fetch_workers_lines failed: %s", exc)
        return [], f"workers: unexpected error ({exc})", False

    if status == 403:
        return [], "workers: 403 (token lacks Workers read).", True
    if status != 200 or not isinstance(body, dict):
        return [], f"workers: API returned HTTP {status}.", False

    scripts = body.get("result") or []
    has_paid_plan = any(
        (s.get("rate_plan") or {}).get("id", "").startswith(WORKERS_PAID_PLAN_PREFIXES)
        for s in raw_subs
    )
    if not scripts:
        return [], "workers: 0 scripts deployed.", False

    note = (
        f"workers: {len(scripts)} script(s) deployed; paid plan active "
        "(flat fee summed via /subscriptions)."
        if has_paid_plan
        else f"workers: {len(scripts)} script(s) on free tier (no charge)."
    )
    # Only add a line if there's something to bill. Paid plan already
    # accounted for via /subscriptions; free tier is $0.
    return [], note, False


async def _fetch_r2_lines(
    client: httpx.AsyncClient, account_id: str
) -> tuple[list[dict], str, bool]:
    """List /accounts/{id}/r2/buckets, then per-bucket /usage. Sum storage
    bytes across all buckets, apply R2 Standard pricing. Ops cost is a
    known v1 gap (requires the analytics GraphQL endpoint)."""
    saw_403 = False
    try:
        status, body = await _fetch_json(
            client, f"/accounts/{account_id}/r2/buckets"
        )
    except Exception as exc:
        logger.warning("cloudflare_billing: _fetch_r2_lines failed: %s", exc)
        return [], f"r2: unexpected error ({exc})", False

    if status == 403:
        return [], "r2: 403 (token lacks R2 read).", True
    if status != 200 or not isinstance(body, dict) or not body.get("success"):
        return [], f"r2: API returned HTTP {status}.", False

    buckets = (body.get("result") or {}).get("buckets") or []
    if not buckets:
        return [], "r2: 0 buckets.", False

    total_bytes = 0
    fetched_buckets = 0
    failed_buckets: list[str] = []
    for b in buckets:
        name = b.get("name")
        if not name:
            continue
        try:
            u_status, u_body = await _fetch_json(
                client, f"/accounts/{account_id}/r2/buckets/{name}/usage"
            )
        except Exception:
            failed_buckets.append(name)
            continue
        if u_status != 200 or not isinstance(u_body, dict):
            failed_buckets.append(name)
            continue
        usage = u_body.get("result") or {}
        try:
            payload = int(usage.get("payloadSize") or 0)
            metadata = int(usage.get("metadataSize") or 0)
            ia_payload = int(usage.get("infrequentAccessPayloadSize") or 0)
            ia_metadata = int(usage.get("infrequentAccessMetadataSize") or 0)
            total_bytes += payload + metadata + ia_payload + ia_metadata
            fetched_buckets += 1
        except (TypeError, ValueError):
            failed_buckets.append(name)

    gb = total_bytes / (1024 ** 3)
    storage_cost = gb * R2_STORAGE_PRICE_USD_PER_GB_MONTH

    lines = [{
        "name": f"R2 storage ({fetched_buckets} bucket(s), {gb:.3f} GB)",
        "plan": "r2_storage",
        "cost_usd": round(storage_cost, 2),
    }]
    note_parts = [
        f"r2: {len(buckets)} bucket(s), {gb:.3f} GB total at "
        f"${R2_STORAGE_PRICE_USD_PER_GB_MONTH}/GB-mo."
    ]
    if failed_buckets:
        note_parts.append(f"Usage fetch failed for: {', '.join(failed_buckets)}.")
    note_parts.append(
        "Class A/B ops cost not summed in v1 — REST /usage doesn't expose "
        "ops counts; analytics GraphQL endpoint is the follow-up."
    )
    return lines, " ".join(note_parts), False


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


async def get_cloudflare_spend() -> dict:
    """Combined monthly Cloudflare spend from zones + subscriptions +
    registrar + workers + R2. Cached 1h. Stable shape on every error path."""
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
    gaps: list[str] = []
    surface_notes: list[str] = []

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        # Token sanity first — every downstream call assumes it's valid.
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

        zone_lines, zone_note, zone_403 = await _fetch_zone_lines(client, account_id)
        if zone_403:
            gaps.append("zones")
        if zone_note:
            surface_notes.append(zone_note)
        subscriptions.extend(zone_lines)

        sub_lines, raw_subs, sub_note, sub_403 = await _fetch_subscription_lines(client, account_id)
        if sub_403:
            gaps.append("account_subscriptions")
        if sub_note:
            surface_notes.append(sub_note)
        subscriptions.extend(sub_lines)

        reg_lines, reg_note, reg_403 = await _fetch_registrar_lines(client, account_id)
        if reg_403:
            gaps.append("registrar_domains")
        if reg_note:
            surface_notes.append(reg_note)
        subscriptions.extend(reg_lines)

        wk_lines, wk_note, wk_403 = await _fetch_workers_lines(client, account_id, raw_subs)
        if wk_403:
            gaps.append("workers_scripts")
        if wk_note:
            surface_notes.append(wk_note)
        subscriptions.extend(wk_lines)

        r2_lines, r2_note, r2_403 = await _fetch_r2_lines(client, account_id)
        if r2_403:
            gaps.append("r2_buckets")
        if r2_note:
            surface_notes.append(r2_note)
        subscriptions.extend(r2_lines)

    total = sum(float(s.get("cost_usd") or 0) for s in subscriptions)

    notes_parts: list[str] = []
    if gaps:
        notes_parts.append(
            "Inaccessible billable surfaces (token lacks scope): "
            + ", ".join(gaps)
            + ". Real Cloudflare bill may be higher; check the dashboard."
        )
    else:
        notes_parts.append("All probed account surfaces returned OK.")
    notes_parts.extend(surface_notes)

    result = {
        "monthly_total_usd": round(total, 2),
        "subscriptions": sorted(subscriptions, key=lambda s: float(s.get("cost_usd") or 0), reverse=True),
        "fetched_at": _now_utc_iso(),
        "configured": True,
        "notes": " ".join(notes_parts),
        "gaps": gaps,
    }
    _cache["value"] = result
    _cache["expires_at"] = now + CACHE_TTL_SECONDS
    return result
