"""Twilio hosting spend — billed truth from Usage Records.

Twilio's billing API is the cleanest of the three providers we sum on the
hosting tab — month-to-date usage records come back fully priced per
category, so ``monthly_total_usd`` here is an actual billed figure (not a
plan-rate estimate like Render and not best-effort like Cloudflare).

Public surface:
    ``async def get_twilio_spend() -> dict``

Response shape:
    {
      "monthly_total_usd": float,
      "usage_by_category": [{"category": str, "description": str, "price_usd": float}, ...],
      "phone_numbers": {"count": int, "monthly_cost": float},
      "balance_usd": float,
      "fetched_at": ISO-8601,
      "configured": bool,
      "notes": str,
    }

Result is cached in-process for 1 hour. Stable shape on every error path
so the UI tile never crashes the Cost tab.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger("bridgedeck.api.twilio_billing")

TWILIO_API_BASE = "https://api.twilio.com"
CACHE_TTL_SECONDS = 3600.0  # 1 hour

# Twilio's Usage Records contain BOTH leaf categories (e.g. ``sms-outbound``)
# and aggregate categories that re-sum their children (e.g. ``sms`` aggregates
# ``sms-outbound`` + ``sms-inbound`` + ...). The ``totalprice`` category is the
# top-level aggregate — i.e. the actual monthly bill — so we use that as the
# authoritative ``monthly_total_usd`` and exclude it from the per-category
# breakdown to avoid implying it's a separate line item.
TOTAL_PRICE_CATEGORY = "totalprice"

# ``phonenumbers`` is the aggregate over phonenumbers-local + phonenumbers-tollfree
# + phonenumbers-emergency etc. Using just the aggregate avoids double-counting
# when both parent and children appear in the records list.
PHONE_RENTAL_AGGREGATE = "phonenumbers"

_cache: dict[str, Any] = {"value": None, "expires_at": 0.0}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _missing_config_response() -> dict:
    missing = [
        k for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN")
        if not (os.environ.get(k) or "").strip()
    ]
    return {
        "monthly_total_usd": 0.0,
        "usage_by_category": [],
        "phone_numbers": {"count": 0, "monthly_cost": 0.0},
        "balance_usd": 0.0,
        "fetched_at": _now_utc_iso(),
        "configured": False,
        "notes": (
            f"Not configured: missing {', '.join(missing)} on the API service "
            "environment. Set both env vars and redeploy to enable this tile."
        ),
    }


async def _fetch_json(client: httpx.AsyncClient, path: str) -> tuple[int, Any]:
    try:
        resp = await client.get(path if path.startswith("http") else f"{TWILIO_API_BASE}{path}")
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, None
    except httpx.HTTPError as exc:
        logger.warning("twilio_billing: request to %s failed: %s", path, exc)
        return 0, None


async def _fetch_all_usage_records(client: httpx.AsyncClient, sid: str) -> list[dict]:
    """Paginate /Usage/Records/ThisMonth.json. Returns every record this
    month. PageSize maxes at 1000 on Twilio's API."""
    out: list[dict] = []
    next_uri: Optional[str] = (
        f"/2010-04-01/Accounts/{sid}/Usage/Records/ThisMonth.json?PageSize=1000"
    )
    while next_uri:
        status, body = await _fetch_json(client, next_uri)
        if status != 200 or not isinstance(body, dict):
            break
        out.extend(body.get("usage_records") or [])
        next_uri = body.get("next_page_uri") or None
    return out


async def _fetch_phone_number_count(client: httpx.AsyncClient, sid: str) -> int:
    """Paginate /IncomingPhoneNumbers.json counting entries. The list endpoint
    doesn't return a total, so we paginate with PageSize=1000."""
    count = 0
    next_uri: Optional[str] = (
        f"/2010-04-01/Accounts/{sid}/IncomingPhoneNumbers.json?PageSize=1000"
    )
    while next_uri:
        status, body = await _fetch_json(client, next_uri)
        if status != 200 or not isinstance(body, dict):
            break
        count += len(body.get("incoming_phone_numbers") or [])
        next_uri = body.get("next_page_uri") or None
    return count


async def _fetch_balance(client: httpx.AsyncClient, sid: str) -> float:
    status, body = await _fetch_json(client, f"/2010-04-01/Accounts/{sid}/Balance.json")
    if status != 200 or not isinstance(body, dict):
        return 0.0
    try:
        return float(body.get("balance") or 0)
    except (TypeError, ValueError):
        return 0.0


async def get_twilio_spend() -> dict:
    """Month-to-date Twilio spend with per-category breakdown, phone-number
    count + rental cost, and current account balance. 1h cache."""
    now = time.monotonic()
    cached = _cache.get("value")
    if cached is not None and now < _cache["expires_at"]:
        return cached

    sid = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
    tok = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
    if not sid or not tok:
        logger.warning(
            "twilio_billing: TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN not set — returning 'not configured'"
        )
        return _missing_config_response()

    auth = httpx.BasicAuth(sid, tok)
    async with httpx.AsyncClient(timeout=20.0, auth=auth) as client:
        records = await _fetch_all_usage_records(client, sid)
        phone_count = await _fetch_phone_number_count(client, sid)
        balance = await _fetch_balance(client, sid)

    # Walk records once: authoritative total = totalprice row;
    # phone rental = phonenumbers aggregate row; breakdown = all other
    # non-zero-priced categories (excluding the totalprice aggregate so it
    # doesn't appear as a redundant "line item" on the tile).
    total = 0.0
    phone_rental_cost = 0.0
    by_cat: list[dict] = []
    for r in records:
        try:
            price = float(r.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        category = r.get("category") or "unknown"
        if category == TOTAL_PRICE_CATEGORY:
            total = price
            continue  # don't surface as a line item
        if category == PHONE_RENTAL_AGGREGATE:
            phone_rental_cost = price
        if price > 0:
            by_cat.append({
                "category": category,
                "description": r.get("description") or category,
                "price_usd": round(price, 4),
            })

    by_cat.sort(key=lambda c: c["price_usd"], reverse=True)
    note_lines = [
        f"Month-to-date billed truth from Twilio Usage Records "
        f"({len(records)} category rows; total taken from 'totalprice' aggregate)."
    ]
    if phone_count and phone_rental_cost == 0:
        note_lines.append(
            f"{phone_count} phone number(s) listed but no 'phonenumbers' rental "
            "category billed yet this month — typical early in the billing cycle."
        )

    result = {
        "monthly_total_usd": round(total, 2),
        "usage_by_category": by_cat,
        "phone_numbers": {
            "count": phone_count,
            "monthly_cost": round(phone_rental_cost, 2),
        },
        "balance_usd": round(balance, 2),
        "fetched_at": _now_utc_iso(),
        "configured": True,
        "notes": " ".join(note_lines),
    }
    _cache["value"] = result
    _cache["expires_at"] = now + CACHE_TTL_SECONDS
    return result
