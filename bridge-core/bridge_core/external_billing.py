"""External billing ingestion — Anthropic + OpenAI org-level usage.

Pulls daily spend from each provider's Admin API and upserts into
`kjcodedeck.external_spend_log`. Run by the daily cron task in api/main.py
(02:00 UTC) or manually via POST /cost/external/ingest.

Verified live 2026-04-28 against both providers:
  - Anthropic:  /v1/organizations/usage_report/messages + /cost_report
                require an Admin Key (sk-ant-admin-...). Regular messages
                key returns 401 "invalid x-api-key".
  - OpenAI:     /v1/organization/usage/completions requires Admin Key
                with `api.usage.read` scope. Project key returns 403
                "Missing scopes".

Both clients fall through silently when their admin key isn't set, so the
ingestion job can run with one provider configured and not the other.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

EXTERNAL_SPEND_TABLE = "kjcodedeck.external_spend_log"
HTTP_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_utc(d: date) -> str:
    return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc) \
        .isoformat().replace("+00:00", "Z")


def _key_hint(key_id: Optional[str]) -> Optional[str]:
    if not key_id:
        return None
    return key_id[-4:]


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class AnthropicBillingClient:
    """Pulls Anthropic org-level usage + cost via the Admin API.

    The Admin API requires a separate `sk-ant-admin-...` key (NOT a regular
    messages key). Generated at console.anthropic.com/settings/admin-keys.
    """

    BASE = "https://api.anthropic.com/v1/organizations"

    def __init__(self, admin_key: str):
        self.admin_key = admin_key
        self._headers = {
            "x-api-key": admin_key,
            "anthropic-version": "2023-06-01",
        }

    async def fetch_usage(self, target_date: date) -> list[dict]:
        starting_at = _iso_utc(target_date)
        ending_at = _iso_utc(target_date + timedelta(days=1))
        params = [
            ("starting_at", starting_at),
            ("ending_at", ending_at),
            ("bucket_width", "1d"),
            ("group_by[]", "model"),
            ("group_by[]", "api_key_id"),
            ("group_by[]", "workspace_id"),
        ]
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(
                f"{self.BASE}/usage_report/messages",
                params=params, headers=self._headers,
            )
            r.raise_for_status()
            return r.json().get("data", [])

    async def fetch_cost(self, target_date: date) -> list[dict]:
        starting_at = _iso_utc(target_date)
        ending_at = _iso_utc(target_date + timedelta(days=1))
        params = [
            ("starting_at", starting_at),
            ("ending_at", ending_at),
            ("bucket_width", "1d"),
            ("group_by[]", "api_key_id"),
            ("group_by[]", "workspace_id"),
        ]
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(
                f"{self.BASE}/cost_report",
                params=params, headers=self._headers,
            )
            r.raise_for_status()
            return r.json().get("data", [])


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class OpenAIBillingClient:
    """Pulls OpenAI org-level usage via the new Admin API.

    Requires an Admin Key with the `api.usage.read` scope. The legacy
    `/v1/usage?date=...` endpoint also exists but returns mostly empty
    buckets in 2026 — Admin API is the canonical path."""

    BASE = "https://api.openai.com/v1/organization"

    # Endpoints we actually care about for KJE traffic. `audio_speech` and
    # `images` exist too but aren't on the empire's hot path; add as needed.
    USAGE_ENDPOINTS = [
        "completions",
        "embeddings",
        "audio_transcriptions",
    ]

    def __init__(self, admin_key: str):
        self.admin_key = admin_key
        self._headers = {"Authorization": f"Bearer {admin_key}"}

    async def fetch_usage(self, target_date: date) -> list[dict]:
        start_ts = int(datetime.combine(target_date, datetime.min.time()).timestamp())
        end_ts   = int(datetime.combine(target_date + timedelta(days=1), datetime.min.time()).timestamp())
        results: list[dict] = []
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            for endpoint in self.USAGE_ENDPOINTS:
                try:
                    r = await client.get(
                        f"{self.BASE}/usage/{endpoint}",
                        params={
                            "start_time": start_ts,
                            "end_time": end_ts,
                            "bucket_width": "1d",
                        },
                        headers=self._headers,
                    )
                    if r.status_code == 200:
                        results.append({"endpoint": endpoint, "data": r.json().get("data", [])})
                    else:
                        logger.warning(
                            "OpenAI usage/%s returned %d: %s",
                            endpoint, r.status_code, r.text[:200],
                        )
                except Exception as exc:
                    logger.warning("OpenAI usage/%s failed: %s", endpoint, exc)
        return results

    async def fetch_costs(self, target_date: date) -> list[dict]:
        """OpenAI has /organization/costs separately. Returns billed truth
        in USD per day. Not all OpenAI Admin keys are scoped for this; we
        gracefully return [] if it fails."""
        start_ts = int(datetime.combine(target_date, datetime.min.time()).timestamp())
        end_ts   = int(datetime.combine(target_date + timedelta(days=1), datetime.min.time()).timestamp())
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            try:
                r = await client.get(
                    f"{self.BASE}/costs",
                    params={
                        "start_time": start_ts,
                        "end_time": end_ts,
                        "bucket_width": "1d",
                    },
                    headers=self._headers,
                )
                if r.status_code == 200:
                    return r.json().get("data", [])
                logger.warning("OpenAI /costs returned %d: %s", r.status_code, r.text[:200])
            except Exception as exc:
                logger.warning("OpenAI /costs failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Ingestion driver
# ---------------------------------------------------------------------------


async def ingest_billing_for_date(
    *,
    supabase_table_fn,
    target_date: date,
    anthropic_admin_key: Optional[str] = None,
    openai_admin_key: Optional[str] = None,
    run_sync_fn=None,
) -> dict:
    """Ingest one day's billing from both providers.

    `supabase_table_fn` is a callable returning a postgrest-py builder for a
    given (schema-qualified) table name — matches the pattern used by
    `api/services/supabase_client.table()`. `run_sync_fn` wraps sync
    supabase-py calls in asyncio.to_thread."""
    summary = {
        "date": target_date.isoformat(),
        "anthropic": {"rows_upserted": 0, "errors": []},
        "openai":    {"rows_upserted": 0, "errors": []},
    }

    if anthropic_admin_key:
        await _ingest_anthropic(
            anthropic_admin_key, target_date,
            supabase_table_fn, run_sync_fn, summary["anthropic"],
        )
    else:
        summary["anthropic"]["errors"].append("ANTHROPIC_ADMIN_API_KEY not set")

    if openai_admin_key:
        await _ingest_openai(
            openai_admin_key, target_date,
            supabase_table_fn, run_sync_fn, summary["openai"],
        )
    else:
        summary["openai"]["errors"].append("OPENAI_ADMIN_API_KEY not set")

    return summary


async def _ingest_anthropic(
    admin_key: str,
    target_date: date,
    supabase_table_fn,
    run_sync_fn,
    bucket_summary: dict,
) -> None:
    try:
        client = AnthropicBillingClient(admin_key)
        usage_buckets, cost_buckets = await asyncio.gather(
            client.fetch_usage(target_date),
            client.fetch_cost(target_date),
        )
    except httpx.HTTPStatusError as exc:
        bucket_summary["errors"].append(
            f"http {exc.response.status_code}: {exc.response.text[:300]}"
        )
        return
    except Exception as exc:
        bucket_summary["errors"].append(f"{type(exc).__name__}: {exc}")
        return

    # Build a lookup keyed by (starts_at, api_key_id, workspace_id) so we can
    # marry usage rows to cost rows that share those grouping keys.
    cost_index: dict[tuple, float] = {}
    for cb in cost_buckets:
        starts_at = cb.get("starts_at")
        for row in cb.get("results", []) or []:
            key = (
                starts_at,
                row.get("api_key_id"),
                row.get("workspace_id"),
            )
            amount = row.get("amount", {})
            if isinstance(amount, dict):
                cost_index[key] = cost_index.get(key, 0.0) + float(amount.get("value", 0) or 0)
            else:
                cost_index[key] = cost_index.get(key, 0.0) + float(amount or 0)

    for ub in usage_buckets:
        starts_at = ub.get("starts_at")
        for row in ub.get("results", []) or []:
            key = (starts_at, row.get("api_key_id"), row.get("workspace_id"))
            cost_usd = round(cost_index.get(key, 0.0), 6)
            payload = {
                "provider": "anthropic",
                "billing_date": target_date.isoformat(),
                "api_key_hint": _key_hint(row.get("api_key_id")),
                "workspace_id": row.get("workspace_id"),
                "model": row.get("model"),
                "tokens_in": (row.get("uncached_input_tokens") or 0)
                            + (row.get("cache_creation_input_tokens") or 0),
                "tokens_out": row.get("output_tokens") or 0,
                "cache_read_tokens": row.get("cache_read_input_tokens") or 0,
                "cache_write_tokens": row.get("cache_creation_input_tokens") or 0,
                "request_count": 1,
                "cost_usd": cost_usd,
                "raw_response": row,
            }
            try:
                await _upsert(supabase_table_fn, run_sync_fn, payload)
                bucket_summary["rows_upserted"] += 1
            except Exception as exc:
                bucket_summary["errors"].append(f"upsert: {exc}")


async def _ingest_openai(
    admin_key: str,
    target_date: date,
    supabase_table_fn,
    run_sync_fn,
    bucket_summary: dict,
) -> None:
    try:
        client = OpenAIBillingClient(admin_key)
        usage_results, cost_buckets = await asyncio.gather(
            client.fetch_usage(target_date),
            client.fetch_costs(target_date),
        )
    except Exception as exc:
        bucket_summary["errors"].append(f"{type(exc).__name__}: {exc}")
        return

    # Map cost (USD) onto a single per-day total — OpenAI cost endpoint
    # doesn't break down by model, so we attribute proportionally to
    # request volume across the usage buckets.
    cost_total = 0.0
    for cb in cost_buckets:
        for row in cb.get("results", []) or []:
            amount = row.get("amount", {})
            if isinstance(amount, dict):
                cost_total += float(amount.get("value", 0) or 0)
            else:
                cost_total += float(amount or 0)

    # Flatten all usage results.
    flat: list[tuple[str, dict]] = []
    for rs in usage_results:
        endpoint = rs.get("endpoint")
        for bucket in rs.get("data", []) or []:
            for item in bucket.get("results", []) or []:
                flat.append((endpoint, item))

    total_requests = sum(int(item.get("num_model_requests") or 0) for _, item in flat) or 1

    for endpoint, item in flat:
        reqs = int(item.get("num_model_requests") or 0)
        share = (reqs / total_requests) if total_requests else 0
        per_row_cost = round(cost_total * share, 6)
        payload = {
            "provider": "openai",
            "billing_date": target_date.isoformat(),
            "api_key_hint": None,
            "workspace_id": item.get("project_id"),
            "model": item.get("model"),
            "tokens_in": item.get("input_tokens") or 0,
            "tokens_out": item.get("output_tokens") or 0,
            "cache_read_tokens": item.get("input_cached_tokens") or 0,
            "cache_write_tokens": 0,
            "request_count": reqs,
            "cost_usd": per_row_cost,
            "raw_response": {"endpoint": endpoint, **item},
        }
        try:
            await _upsert(supabase_table_fn, run_sync_fn, payload)
            bucket_summary["rows_upserted"] += 1
        except Exception as exc:
            bucket_summary["errors"].append(f"upsert: {exc}")


async def _upsert(supabase_table_fn, run_sync_fn, payload: dict) -> None:
    """Upsert one row keyed on (provider, billing_date, api_key_hint, model,
    workspace_id) — matches the UNIQUE constraint in the migration."""
    def _do():
        return (
            supabase_table_fn("external_spend_log")
            .upsert(
                payload,
                on_conflict="provider,billing_date,api_key_hint,model,workspace_id",
            )
            .execute()
        )
    if run_sync_fn is None:
        # Last-resort: call sync directly. Caller should pass run_sync_fn
        # in production so we don't block the event loop.
        _do()
    else:
        await run_sync_fn(_do)


# ---------------------------------------------------------------------------
# Daily cron entrypoint
# ---------------------------------------------------------------------------


async def daily_cron(*, supabase_table_fn, run_sync_fn=None) -> dict:
    """Pull yesterday's billing for both providers. Reads admin keys from
    env at call-time so a hot-reload of secrets is picked up next run."""
    yesterday = date.today() - timedelta(days=1)
    return await ingest_billing_for_date(
        supabase_table_fn=supabase_table_fn,
        run_sync_fn=run_sync_fn,
        target_date=yesterday,
        anthropic_admin_key=os.getenv("ANTHROPIC_ADMIN_API_KEY"),
        openai_admin_key=os.getenv("OPENAI_ADMIN_API_KEY"),
    )
