"""Cost intelligence — read endpoints + cap CRUD.

Backed by `kjcodedeck.cost_log` (every billable call) and
`kjcodedeck.cost_caps` (empire/project/per-turn ceilings). Both tables ship
in `supabase/migrations/20260427_cost_intel.sql`. If the migration hasn't
been applied yet, every endpoint here returns an empty/zeroed payload
instead of 500'ing — the UI then renders zeros until the user runs the SQL.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import history_logger
from services.supabase_client import run_sync, table

logger = logging.getLogger("bridgedeck.api.cost")

router = APIRouter()

COST_LOG = "cost_log"
COST_CAPS = "cost_caps"
RATE_LIMIT_BLOCKS = "rate_limit_blocks"
TURN_OUTCOMES = "turn_outcomes"
COST_BY_INTENT_VIEW = "cost_by_intent_30d"
SESSION_HEALTH_VIEW = "session_health_score"
EXTERNAL_SPEND_LOG = "external_spend_log"
EMPIRE_SPEND_VIEW = "empire_spend_30d"
RECONCILIATION_VIEW = "spend_reconciliation_7d"

# Phase 3.2 — empire-wide self-reporting. Internal cost_log source_systems
# (the auxiliary BridgeDeck pipeline calls) are filtered out of the
# coverage report so they don't pollute the "which KJE product is
# instrumented" picture.
EXPECTED_PRODUCTS = [
    "kjwidgetz", "kjle", "demoboosterz", "demoenginez", "siteenginez",
    "unhidelocal", "voicedropz", "kj_autonomous", "agentenginez",
    "daycaremarketerz", "reviewbombz", "kjpde", "kj_salesagentz",
    "kj_testenginez", "kj_bridgedeck", "iamstillhere", "telehealth",
    "financeiq", "inkhaus", "offerenginez",
]
INTERNAL_SOURCES = {"bridge", "intent", "summarizer", "whisper", "cc_session", "bridge_compress"}

# kj_bridgedeck never writes cost_log rows under its own slug — it writes
# under the internal sub-source names ("bridge", "intent", "summarizer",
# "cc_session", "whisper", "bridge_compress"). For coverage attribution
# (which product is instrumented), we roll those internal sources back
# up to the kj_bridgedeck product. Other endpoints (/cost/by-source,
# /cost/timeline) keep raw source_system so the per-source breakdown
# stays meaningful.
INTERNAL_KJ_BRIDGEDECK_SOURCES = {
    "bridge", "intent", "summarizer",
    "cc_session", "whisper", "bridge_compress",
}


def map_source_to_product(source_system: str) -> str:
    """Roll up internal Bridge sub-sources into the kj_bridgedeck product."""
    if source_system in INTERNAL_KJ_BRIDGEDECK_SOURCES:
        return "kj_bridgedeck"
    return source_system


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _safe_select_costs(*, since: datetime, project_slug: Optional[str] = None) -> list[dict]:
    """Pull cost_log rows for an aggregation window. Returns [] on missing
    table (migration not applied) so callers don't need to special-case it."""
    def _do():
        q = (
            table(COST_LOG)
            .select("*")
            .gte("created_at", since.isoformat())
            .order("created_at", desc=False)
        )
        if project_slug:
            q = q.eq("project_slug", project_slug)
        return q.execute()

    try:
        res = await run_sync(_do)
        return res.data or []
    except Exception as exc:
        logger.warning("cost_log select failed (migration applied?): %s", exc)
        return []


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# GET /cost/summary
# ---------------------------------------------------------------------------


@router.get("/summary")
async def summary() -> dict:
    now = datetime.now(timezone.utc)
    today = _start_of_day(now)
    week = now - timedelta(days=7)
    month = now - timedelta(days=30)

    rows_month = await _safe_select_costs(since=month)

    def _sum(rows: list[dict], gte: datetime) -> float:
        return float(
            sum(
                float(r.get("cost_usd") or 0)
                for r in rows
                if r.get("created_at") and r["created_at"] >= gte.isoformat()
            )
        )

    today_total = _sum(rows_month, today)
    week_total = _sum(rows_month, week)
    month_total = _sum(rows_month, month)

    by_project: dict[str, float] = defaultdict(float)
    by_session: dict[str, float] = defaultdict(float)
    for r in rows_month:
        slug = r.get("project_slug") or "—"
        by_project[slug] += float(r.get("cost_usd") or 0)
        sid = r.get("session_id")
        if sid:
            by_session[sid] += float(r.get("cost_usd") or 0)

    top_projects = sorted(
        ({"project_slug": k, "total_usd": round(v, 4)} for k, v in by_project.items()),
        key=lambda x: x["total_usd"], reverse=True,
    )[:10]
    top_sessions = sorted(
        ({"session_id": k, "total_usd": round(v, 4)} for k, v in by_session.items()),
        key=lambda x: x["total_usd"], reverse=True,
    )[:10]

    return {
        "today": round(today_total, 4),
        "week": round(week_total, 4),
        "month": round(month_total, 4),
        "top_projects": top_projects,
        "top_sessions": top_sessions,
    }


# ---------------------------------------------------------------------------
# GET /cost/timeline?days=30
# ---------------------------------------------------------------------------


@router.get("/timeline")
async def timeline(days: int = 30) -> dict:
    days = max(1, min(days, 90))
    since = _start_of_day(datetime.now(timezone.utc) - timedelta(days=days - 1))
    rows = await _safe_select_costs(since=since)

    buckets: dict[str, dict[str, float]] = {}
    for r in rows:
        ts = r.get("created_at") or ""
        date = ts[:10] if len(ts) >= 10 else "unknown"
        bucket = buckets.setdefault(date, {"total": 0.0})
        cost = float(r.get("cost_usd") or 0)
        bucket["total"] += cost
        src = r.get("source_system") or "other"
        bucket[src] = bucket.get(src, 0.0) + cost

    # Fill missing days with zeros so the heatmap renders without gaps.
    out: list[dict] = []
    for i in range(days):
        d = (since + timedelta(days=i)).date().isoformat()
        b = buckets.get(d, {"total": 0.0})
        b = {k: round(v, 4) for k, v in b.items()}
        out.append({"date": d, **b})
    return {"timeline": out, "days": days}


# ---------------------------------------------------------------------------
# GET /cost/by-project?days=7
# ---------------------------------------------------------------------------


@router.get("/by-project")
async def by_project(days: int = 7) -> dict:
    days = max(1, min(days, 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await _safe_select_costs(since=since)
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"total": 0.0})
    for r in rows:
        slug = r.get("project_slug") or "—"
        cost = float(r.get("cost_usd") or 0)
        bucket = totals[slug]
        bucket["total"] += cost
        bucket[r.get("source_system") or "other"] = (
            bucket.get(r.get("source_system") or "other", 0.0) + cost
        )
    out = sorted(
        ({"project_slug": k, **{kk: round(vv, 4) for kk, vv in v.items()}}
         for k, v in totals.items()),
        key=lambda x: x["total"], reverse=True,
    )
    return {"projects": out, "days": days}


# ---------------------------------------------------------------------------
# GET /cost/by-source?days=7
# ---------------------------------------------------------------------------


@router.get("/by-source")
async def by_source(days: int = 7) -> dict:
    days = max(1, min(days, 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await _safe_select_costs(since=since)
    totals: dict[str, float] = defaultdict(float)
    for r in rows:
        totals[r.get("source_system") or "other"] += float(r.get("cost_usd") or 0)
    return {
        "sources": {k: round(v, 4) for k, v in totals.items()},
        "days": days,
    }


# ---------------------------------------------------------------------------
# GET /cost/live
# ---------------------------------------------------------------------------


@router.get("/live")
async def live() -> dict:
    now = datetime.now(timezone.utc)
    today = _start_of_day(now)
    today_rows = await _safe_select_costs(since=today)
    today_total = float(sum(float(r.get("cost_usd") or 0) for r in today_rows))

    # Rough burn-rate from active live_sessions.
    burn_rate = 0.0
    try:
        def _live_sessions():
            return (
                table("live_sessions")
                .select("cost_usd,started_at,status")
                .neq("status", "ended")
                .execute()
            )
        live_res = await run_sync(_live_sessions)
        live_rows = live_res.data or []
        burn_rate = float(sum(float(r.get("cost_usd") or 0) for r in live_rows))
    except Exception as exc:
        logger.debug("burn-rate calc failed: %s", exc)

    return {
        "today": round(today_total, 4),
        "current_bridge_turn": 0.0,  # filled by client during a streaming turn
        "active_sessions_burn_rate": round(burn_rate, 4),
        "as_of": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /cost/caps   PATCH /cost/caps/{scope}
# ---------------------------------------------------------------------------


@router.get("/caps")
async def list_caps() -> dict:
    try:
        res = await run_sync(lambda: table(COST_CAPS).select("*").execute())
        return {"caps": res.data or []}
    except Exception as exc:
        logger.warning("cost_caps select failed: %s", exc)
        return {"caps": []}


class CapPatch(BaseModel):
    cap_usd: Optional[float] = None
    behavior: Optional[str] = None
    enabled: Optional[bool] = None


# ---------------------------------------------------------------------------
# GET /cost/by-intent
# ---------------------------------------------------------------------------


@router.get("/by-intent")
async def by_intent() -> dict:
    """Per-intent rollup for the last 30 days. Backed by the
    `cost_by_intent_30d` view added in cost_intel_phase2.sql. Returns
    empty list if the view doesn't exist yet."""
    try:
        res = await run_sync(
            lambda: table(COST_BY_INTENT_VIEW)
            .select("*").order("total_cost", desc=True).execute()
        )
        return {"intents": res.data or []}
    except Exception as exc:
        logger.warning("by-intent view select failed: %s", exc)
        return {"intents": []}


@router.get("/by-intent/recommendations")
async def by_intent_recommendations() -> dict:
    """Cheap heuristic: any intent whose avg_cost > $0.05 AND avg_in > 5K
    tokens is flagged as a candidate for tighter context scoping."""
    try:
        res = await run_sync(
            lambda: table(COST_BY_INTENT_VIEW).select("*").execute()
        )
        rows = res.data or []
    except Exception as exc:
        logger.warning("recommendations select failed: %s", exc)
        rows = []
    recs: list[dict] = []
    for r in rows:
        avg_cost = float(r.get("avg_cost") or 0)
        avg_in = float(r.get("avg_in") or 0)
        avg_out = float(r.get("avg_out") or 0)
        intent = r.get("intent") or "?"
        if avg_cost > 0.05 and avg_in > 5000:
            recs.append({
                "intent": intent,
                "avg_cost": round(avg_cost, 4),
                "avg_tokens_in": int(avg_in),
                "recommendation": (
                    f"`{intent}` averages ${avg_cost:.3f}/turn with {int(avg_in)} input "
                    "tokens. Consider tightening the context handler in "
                    "bridge_core/context.py or routing to Haiku."
                ),
            })
        if avg_out and avg_in / max(avg_out, 1) > 50:
            recs.append({
                "intent": intent,
                "ratio_in_to_out": round(avg_in / max(avg_out, 1), 1),
                "recommendation": (
                    f"`{intent}` reads {int(avg_in)/max(avg_out,1):.0f}× more "
                    "context than it produces. Likely over-fetching."
                ),
            })
    return {"recommendations": recs}


# ---------------------------------------------------------------------------
# GET /cost/wasted-cost   GET /cost/refund-worthy
# ---------------------------------------------------------------------------


async def _wasted_aggregate(days: int = 30, refund_only: bool = False) -> dict:
    """Sum cost_usd for bridge turns the user tagged 'wasted' (or
    'error_refund' when refund_only=True). Joined client-side because
    the supabase shim doesn't model FKs."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        outcomes_res = await run_sync(
            lambda: table(TURN_OUTCOMES)
            .select("*").gte("tagged_at", since.isoformat()).execute()
        )
        outcomes = outcomes_res.data or []
    except Exception as exc:
        logger.warning("turn_outcomes select failed: %s", exc)
        outcomes = []
    if refund_only:
        outcomes = [o for o in outcomes if o.get("outcome") == "error_refund"]
    else:
        outcomes = [o for o in outcomes if o.get("outcome") in ("wasted", "error_refund")]
    if not outcomes:
        return {"total_usd": 0.0, "turns": 0, "details": []}
    turn_ids = [o["turn_id"] for o in outcomes if o.get("turn_id")]
    try:
        cost_res = await run_sync(
            lambda: table(COST_LOG).select("*").in_("turn_id", turn_ids).execute()
        )
        cost_rows = cost_res.data or []
    except Exception as exc:
        logger.warning("cost_log lookup failed: %s", exc)
        cost_rows = []
    by_turn = {r.get("turn_id"): r for r in cost_rows if r.get("turn_id")}
    details: list[dict] = []
    total = 0.0
    for o in outcomes:
        c = by_turn.get(o.get("turn_id"))
        usd = float((c or {}).get("cost_usd") or 0)
        total += usd
        details.append({
            "turn_id": o.get("turn_id"),
            "outcome": o.get("outcome"),
            "cost_usd": round(usd, 4),
            "intent": (c or {}).get("intent"),
            "tagged_at": o.get("tagged_at"),
        })
    return {
        "total_usd": round(total, 4),
        "turns": len(outcomes),
        "details": sorted(details, key=lambda d: d["cost_usd"], reverse=True)[:50],
    }


@router.get("/wasted-cost")
async def wasted_cost(days: int = 30) -> dict:
    return await _wasted_aggregate(days=days, refund_only=False)


@router.get("/refund-worthy")
async def refund_worthy(days: int = 30) -> dict:
    return await _wasted_aggregate(days=days, refund_only=True)


# ---------------------------------------------------------------------------
# GET /cost/rate-limit
# ---------------------------------------------------------------------------


@router.get("/rate-limit")
async def rate_limit_state() -> dict:
    """Live rate-limit usage for each provider + recent block events."""
    # Live counters from the in-process tracker (single Render worker).
    try:
        from bridge_core import all_trackers
        live = [t.snapshot() for t in all_trackers()]
    except Exception as exc:
        logger.warning("rate-limiter import failed: %s", exc)
        live = []

    # Last 24h of block events.
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    try:
        blocks_res = await run_sync(
            lambda: table(RATE_LIMIT_BLOCKS)
            .select("*").gte("blocked_at", since.isoformat())
            .order("blocked_at", desc=True).limit(50).execute()
        )
        blocks = blocks_res.data or []
    except Exception as exc:
        logger.warning("rate_limit_blocks select failed: %s", exc)
        blocks = []

    return {"live": live, "recent_blocks": blocks}


@router.patch("/caps/{scope}")
async def patch_cap(scope: str, body: CapPatch) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(400, "no fields to update")
    if "behavior" in patch and patch["behavior"] not in ("warn", "haiku_force", "hard_stop"):
        raise HTTPException(400, "behavior must be warn|haiku_force|hard_stop")
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()

    def _do():
        return (
            table(COST_CAPS).upsert({"scope": scope, **patch}, on_conflict="scope").execute()
        )

    try:
        res = await run_sync(_do)
    except Exception as exc:
        logger.warning("cost_caps upsert failed: %s", exc)
        raise HTTPException(500, f"cost_caps upsert failed: {exc}")

    await history_logger.log(
        event_type="setting.cost_cap_updated",
        event_category="setting",
        actor="api",
        action=f"upsert cap {scope}",
        target=scope,
        after_state=patch,
    )
    rows = res.data or []
    return rows[0] if rows else {"scope": scope, **patch}


# ---------------------------------------------------------------------------
# Phase 3.1 — External billing (Anthropic + OpenAI Admin API ingestion)
# ---------------------------------------------------------------------------


@router.get("/external")
async def get_external_spend(days: int = 7, provider: Optional[str] = None) -> dict:
    """Returns billed truth from Anthropic / OpenAI org-level usage. Empty
    when the migration hasn't run or no admin keys are configured."""
    days = max(1, min(days, 90))
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()

    def _do():
        q = (
            table(EXTERNAL_SPEND_LOG)
            .select("*")
            .gte("billing_date", cutoff)
            .order("billing_date", desc=True)
        )
        if provider:
            q = q.eq("provider", provider)
        return q.execute()

    try:
        res = await run_sync(_do)
        return {"days": days, "provider": provider, "rows": res.data or []}
    except Exception as exc:
        logger.warning("external spend select failed: %s", exc)
        return {"days": days, "provider": provider, "rows": []}


@router.get("/empire-summary")
async def get_empire_summary() -> dict:
    """Total empire AI spend — billed truth from external_spend_log.
    Returns today / week / month aggregates broken down by provider."""
    now = datetime.now(timezone.utc)
    today_iso = now.date().isoformat()
    week_iso  = (now.date() - timedelta(days=7)).isoformat()
    month_iso = (now.date() - timedelta(days=30)).isoformat()

    async def _fetch_since(date_iso: str) -> list[dict]:
        def _do():
            return (
                table(EXTERNAL_SPEND_LOG)
                .select("provider,cost_usd")
                .gte("billing_date", date_iso)
                .execute()
            )
        try:
            res = await run_sync(_do)
            return res.data or []
        except Exception as exc:
            logger.warning("empire-summary fetch failed: %s", exc)
            return []

    today_rows = await _fetch_since(today_iso)
    week_rows  = await _fetch_since(week_iso)
    month_rows = await _fetch_since(month_iso)

    def _aggregate(rows: list[dict]) -> dict:
        by_provider: dict[str, float] = {}
        total = 0.0
        for r in rows:
            p = r.get("provider") or "unknown"
            c = float(r.get("cost_usd") or 0)
            by_provider[p] = by_provider.get(p, 0.0) + c
            total += c
        return {
            "total": round(total, 4),
            "by_provider": {k: round(v, 4) for k, v in by_provider.items()},
        }

    return {
        "today": _aggregate(today_rows),
        "week":  _aggregate(week_rows),
        "month": _aggregate(month_rows),
        "as_of": now.isoformat(),
    }


@router.get("/reconciliation")
async def get_reconciliation() -> dict:
    """Logged (cost_log) vs billed (external_spend_log) variance from the
    `spend_reconciliation_7d` view. Returns empty when the view doesn't
    exist yet."""
    def _do():
        return table(RECONCILIATION_VIEW).select("*").execute()
    try:
        res = await run_sync(_do)
        return {"reconciliation": res.data or []}
    except Exception as exc:
        logger.warning("reconciliation view select failed: %s", exc)
        return {"reconciliation": []}


@router.post("/external/ingest")
async def trigger_ingestion(days_back: int = 1) -> dict:
    """Manual trigger for billing ingestion — useful for backfill.
    Requires ANTHROPIC_ADMIN_API_KEY and/or OPENAI_ADMIN_API_KEY in env."""
    days_back = max(1, min(days_back, 30))

    try:
        from bridge_core.external_billing import ingest_billing_for_date
    except ImportError as exc:
        raise HTTPException(500, f"bridge_core.external_billing not importable: {exc}")

    import os as _os
    a_key = _os.environ.get("ANTHROPIC_ADMIN_API_KEY")
    o_key = _os.environ.get("OPENAI_ADMIN_API_KEY")
    if not a_key and not o_key:
        raise HTTPException(
            400,
            "Neither ANTHROPIC_ADMIN_API_KEY nor OPENAI_ADMIN_API_KEY is set "
            "in the API environment. See docs/POST_DEPLOY.md or the Phase 3.1 "
            "build prompt for the one-time setup.",
        )

    today = datetime.now(timezone.utc).date()
    results: list[dict] = []
    for i in range(days_back):
        target = today - timedelta(days=i + 1)
        summary = await ingest_billing_for_date(
            supabase_table_fn=table,
            run_sync_fn=run_sync,
            target_date=target,
            anthropic_admin_key=a_key,
            openai_admin_key=o_key,
        )
        results.append(summary)

    await history_logger.log(
        event_type="billing.ingest_manual",
        event_category="action",
        actor="api",
        action=f"backfill {days_back} day(s)",
        details={"days": days_back, "summary": results},
    )
    return {"ingested": results}


# ---------------------------------------------------------------------------
# Phase 3.2 — Empire-wide self-reporting (replaces blocked Anthropic Admin API)
# ---------------------------------------------------------------------------


class CostIngestPayload(BaseModel):
    """Payload posted by every KJE product after each Anthropic/OpenAI call.

    `source_system` identifies the product (e.g. 'agentenginez', 'kjle').
    `cost_usd` is computed client-side via kje_cost_logger.calc_anthropic_cost
    or calc_openai_cost — never trust the model name alone."""
    source_system: str = Field(..., description="Product slug, e.g. 'agentenginez'")
    project_slug: Optional[str] = None
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    turn_id: Optional[str] = None
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float
    intent: Optional[str] = None
    duration_ms: Optional[int] = None
    metadata: Optional[dict] = None


@router.post("/ingest")
async def ingest_cost(payload: CostIngestPayload) -> dict:
    """Empire-wide cost reporting. Any KJE product POSTs here after each
    Anthropic / OpenAI call. Returns cap_status if any cost cap is
    approaching or breached.

    Auth via the existing AdminAuthMiddleware (Bearer BRIDGEDECK_ADMIN_KEY)."""
    # cost_log doesn't have a top-level cache_*_tokens column, so we stash
    # those plus any client-side metadata in the JSONB-friendly fields.
    # `details` doesn't exist on cost_log either; the schema has individual
    # columns. We can't add columns without a migration, so instead we route
    # cache tokens to project_slug-suffixed metadata only when present.
    row = {
        "source_system": payload.source_system,
        "project_slug": payload.project_slug,
        "session_id": payload.session_id,
        "conversation_id": payload.conversation_id,
        "turn_id": payload.turn_id,
        "model": payload.model,
        "tokens_in": payload.tokens_in,
        "tokens_out": payload.tokens_out,
        "cost_usd": float(payload.cost_usd),
        "intent": payload.intent,
        "duration_ms": payload.duration_ms,
    }
    row = {k: v for k, v in row.items() if v is not None}

    def _do():
        return table(COST_LOG).insert(row).execute()

    try:
        await run_sync(_do)
    except Exception as exc:
        logger.warning("cost_log insert failed: %s", exc)
        raise HTTPException(500, f"cost_log insert failed: {exc}")

    cap_status = await _check_caps_for_source(payload.cost_usd)

    return {
        "logged": True,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "cap_status": cap_status,
    }


async def _check_caps_for_source(incremental_cost: float) -> Any:
    """Returns the cap-status payload for the empire_daily cap if today's
    cost_log sum + the incremental call would breach it. `'ok'` otherwise."""
    today_iso = datetime.now(timezone.utc).date().isoformat()

    def _today_total():
        return (
            table(COST_LOG)
            .select("cost_usd")
            .gte("created_at", today_iso)
            .execute()
        )

    def _enabled_caps():
        return table(COST_CAPS).select("*").eq("enabled", True).execute()

    try:
        totals_res = await run_sync(_today_total)
        caps_res = await run_sync(_enabled_caps)
    except Exception as exc:
        logger.debug("cap check soft-failed: %s", exc)
        return "ok"

    today_sum = float(sum(float(r.get("cost_usd") or 0) for r in (totals_res.data or [])))
    statuses: list[dict] = []
    for cap in (caps_res.data or []):
        if cap.get("scope") != "empire_daily":
            continue
        cap_usd = float(cap.get("cap_usd") or 0)
        if cap_usd <= 0:
            continue
        if today_sum + float(incremental_cost) >= cap_usd:
            statuses.append({
                "scope": cap["scope"],
                "behavior": cap.get("behavior") or "warn",
                "current": round(today_sum, 4),
                "cap": cap_usd,
            })
    return statuses if statuses else "ok"


@router.get("/coverage")
async def get_product_coverage() -> dict:
    """Per-KJE-product instrumentation snapshot from the last 24h of
    cost_log. Internal BridgeDeck source_systems (bridge, intent, etc) are
    excluded so the report shows ONLY external products' coverage."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    def _do():
        return (
            table(COST_LOG)
            .select("source_system,project_slug,cost_usd,created_at")
            .gte("created_at", cutoff)
            .execute()
        )

    try:
        res = await run_sync(_do)
        rows = res.data or []
    except Exception as exc:
        logger.warning("coverage select failed: %s", exc)
        rows = []

    # Aggregate by PRODUCT (after rolling internal Bridge sub-sources up to
    # kj_bridgedeck). A product is instrumented iff at least one cost_log
    # row in the last 24h maps to it.
    by_product: dict[str, dict] = {}
    for r in rows:
        ss = r.get("source_system") or "unknown"
        product = map_source_to_product(ss)
        bucket = by_product.setdefault(product, {"calls": 0, "cost_24h": 0.0, "last_seen": None})
        bucket["calls"] += 1
        bucket["cost_24h"] += float(r.get("cost_usd") or 0)
        ts = r.get("created_at") or ""
        if not bucket["last_seen"] or ts > bucket["last_seen"]:
            bucket["last_seen"] = ts

    coverage: list[dict] = []
    for product in EXPECTED_PRODUCTS:
        d = by_product.get(product)
        coverage.append({
            "product": product,
            "instrumented": d is not None,
            "last_seen": d["last_seen"] if d else None,
            "calls_24h": d["calls"] if d else 0,
            "cost_24h": round(d["cost_24h"], 4) if d else 0,
        })

    unexpected = [
        {
            "product": p,
            "calls_24h": d["calls"],
            "cost_24h": round(d["cost_24h"], 4),
            "last_seen": d["last_seen"],
        }
        for p, d in by_product.items()
        if p not in EXPECTED_PRODUCTS
    ]

    return {
        "coverage": coverage,
        "unexpected_sources": sorted(unexpected, key=lambda x: x["cost_24h"], reverse=True),
        "internal_sources_excluded": sorted(INTERNAL_SOURCES),
    }
