"""BridgeChatService — orchestrates one chat turn end-to-end.

Pipeline:
    voice? → transcribe → classify intent → gather sources → choose model →
    stream Claude → parse directives → queue actions → persist turn → auto-save

The service yields `SSEEvent` objects. The FastAPI layer formats and flushes
them to the client; bridge_core has no HTTP concerns of its own.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

from anthropic import AsyncAnthropic

from shared.contracts import BridgeChatRequest, BridgeSources

from .claude_stream import (
    COST_TABLE,
    DEFAULT_RATES,
    MAX_OUTPUT_TOKENS_DEFAULT,
    MAX_OUTPUT_TOKENS_HARD_CAP,
    SSEEvent,
    stream_claude_response,
)
from .context import ContextGatherer
from .directives import parse_directives, strip_directives
from .intent import IntentRouter
from .prompts import build_cached_system_blocks, build_system_prompt
from .rate_limiter import (
    anthropic_input_tokens_tracker,
    wait_for_capacity,
)
from .utils import now_iso
from .voice import VoiceService

logger = logging.getLogger(__name__)

DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
DEFAULT_SONNET = "claude-sonnet-4-5"

# Intent routing. FAST_INTENTS always go to Haiku unless force_model="sonnet".
# Reasoning intents need Sonnet's tool-use + multi-hop synthesis.
FAST_INTENTS = {"status_query", "fact_recall", "cost_query", "session_history"}
HAIKU_INTENTS = FAST_INTENTS | {"save_memory", "general"}
SONNET_INTENTS = {"next_action", "empire_summary", "launch_session"}

BRIDGE_CONVERSATIONS_TABLE = "kjcodedeck.bridge_conversations"
BRIDGE_TURNS_TABLE = "kjcodedeck.bridge_turns"
ACTION_QUEUE_TABLE = "kjcodedeck.action_queue"
HISTORY_LOG_TABLE = "kjcodedeck.history_log"
COST_LOG_TABLE = "kjcodedeck.cost_log"
COST_CAPS_TABLE = "kjcodedeck.cost_caps"
RATE_LIMIT_BLOCKS_TABLE = "kjcodedeck.rate_limit_blocks"
AUTO_SAVE_TURN_THRESHOLD = 6

# GUARDRAIL 2 — token budget enforcement.
# Phase 2: lowered from 120K → 35K because Anthropic org-level rate limit
# is 50K input tokens/minute. We want headroom for the system-prompt body
# + cache-creation overhead even on a fresh cache miss. Empire context
# alone has been observed at 148K tokens — those queries now hit the
# hard-truncate path and end up with a ~25K-char excerpt instead of a 429.
MAX_CONTEXT_TOKENS = 35_000
MAX_HISTORY_TURNS = 4
LOW_CONTEXT_THRESHOLD = 3                   # F9 — empty-context warning
PREEMPTIVE_HAIKU_THRESHOLD_TOKENS = 15_000  # over this, force Haiku
HARD_TRUNCATE_CHAR_CAP = 25_000             # final stop-gap on context dump


def estimate_tokens(text: str) -> int:
    """Rough char-to-token estimate. 1 token ~ 4 chars for English."""
    if not text:
        return 0
    return len(text) // 4


def _sources_token_estimate(sources: Any) -> int:
    if sources is None:
        return 0
    if hasattr(sources, "model_dump_json"):
        return estimate_tokens(sources.model_dump_json())
    try:
        return estimate_tokens(json.dumps(sources, default=str))
    except Exception:
        return estimate_tokens(str(sources))


def _trim_sources(sources: BridgeSources) -> BridgeSources:
    """Hard-trim a BridgeSources bundle when context is over budget."""
    sources.handoffs = sources.handoffs[:10]
    sources.memories = sources.memories[:5]
    sources.cards = sources.cards[:3]
    return sources


def _estimate_turn_cost(
    model: str, tokens_in_estimate: int, tokens_out_estimate: int
) -> float:
    rates = COST_TABLE.get(model, DEFAULT_RATES)
    return (
        tokens_in_estimate * rates["in"] / 1_000_000
        + tokens_out_estimate * rates["out"] / 1_000_000
    )


class BridgeChatService:
    """Streaming chat service. Instantiated once per process."""

    def __init__(
        self,
        anthropic_client: AsyncAnthropic,
        brain_url: str,
        brain_key: str,
        supabase_client: Any,
        voice_service: VoiceService | None = None,
        settings_cache: Any = None,
        brain_save_fn: Any = None,
    ):
        self.anthropic = anthropic_client
        self.intent_router = IntentRouter(anthropic_client)
        self.context_gatherer = ContextGatherer(brain_url, brain_key, supabase_client)
        self.voice = voice_service or VoiceService()
        self.supabase = supabase_client
        self.settings_cache = settings_cache
        self.brain_save_fn = brain_save_fn

    # ------------------------------------------------------------------
    # Public streaming entrypoint
    # ------------------------------------------------------------------

    async def chat(self, request: BridgeChatRequest) -> AsyncGenerator[SSEEvent, None]:
        turn_started = time.time()

        # 0. (Phase 2) Read global panic switch. cheap_mode pins the model
        # to Haiku, skips voice synthesis, halves the output cap. Settable
        # from the Cost admin tab so Jim can throttle empire-wide spend
        # with one click.
        cheap_mode = bool(await self._setting("bridge", "cheap_mode", False))
        cache_enabled = bool(
            await self._setting("bridge", "prompt_caching_enabled", True)
        )
        auto_retry = bool(
            await self._setting("bridge", "auto_retry_on_rate_limit", True)
        )
        if cheap_mode:
            yield SSEEvent(event="cheap_mode", data=json.dumps({"active": True}))

        # 1. Voice input → transcribe
        if request.voice_input and request.audio_base64:
            voice_started = time.time()
            transcript = await self.voice.transcribe(request.audio_base64)
            request.message = transcript
            yield SSEEvent(event="transcript", data=json.dumps({"text": transcript}))
            await self._log_cost(
                source_system="whisper",
                model="whisper-1",
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.006 * max(1, len(request.audio_base64) // 200_000),
                conversation_id=str(request.conversation_id) if request.conversation_id else None,
                duration_ms=int((time.time() - voice_started) * 1000),
            )

        # 2. Load + (F7) compress conversation history
        conv_id = request.conversation_id or uuid4()
        conv_history = await self._load_history(conv_id)
        if len(conv_history) > MAX_HISTORY_TURNS * 2:  # *2 because user+assistant per turn
            digest = await self._compress_history(conv_id, conv_history)
            if digest:
                yield SSEEvent(
                    event="history_compressed",
                    data=json.dumps({"compressed_into": digest[:120] + "…"}),
                )
                conv_history = [
                    {"role": "user", "content": f"[earlier conversation digest]\n{digest}"},
                    *conv_history[-MAX_HISTORY_TURNS * 2 :],
                ]

        # 3. Classify intent
        intent_started = time.time()
        intent_data = await self.intent_router.classify(request.message)
        yield SSEEvent(event="intent", data=json.dumps(intent_data))
        await self._log_cost(
            source_system="intent",
            model=getattr(self.intent_router, "model", None),
            tokens_in=estimate_tokens(request.message),
            tokens_out=80,
            cost_usd=_estimate_turn_cost(
                getattr(self.intent_router, "model", "") or DEFAULT_HAIKU,
                estimate_tokens(request.message),
                80,
            ),
            intent=intent_data.get("intent"),
            project_slug=intent_data.get("project_slug"),
            conversation_id=str(conv_id),
            duration_ms=int((time.time() - intent_started) * 1000),
        )

        # 4. Gather context
        try:
            sources = await self.context_gatherer.gather(
                intent=intent_data["intent"],
                project_slug=intent_data.get("project_slug"),
                message=request.message,
                time_range_days=intent_data.get("time_range_days"),
            )
        except Exception as exc:
            logger.exception("context gather failed: %s", exc)
            sources = BridgeSources()
        yield SSEEvent(event="sources", data=sources.model_dump_json())

        # 5. Choose model. Cheap mode overrides everything; otherwise the
        # FAST_INTENT routing applies (F5).
        if cheap_mode:
            model = await self._setting("bridge", "haiku_model", DEFAULT_HAIKU)
        else:
            model = await self._choose_model(intent_data["intent"], request.force_model)

        # 6. (F11) Cap enforcement — empire_daily / empire_weekly / project_daily.
        caps = await self._load_caps()
        cap_violations: list[dict] = []
        for cap in caps:
            scope = cap.get("scope", "")
            spent = await self._spend_in_scope(scope, intent_data.get("project_slug"))
            if spent is None or float(cap.get("cap_usd") or 0) <= 0:
                continue
            if spent < float(cap["cap_usd"]):
                continue
            behavior = cap.get("behavior") or "warn"
            cap_violations.append(
                {"scope": scope, "spent": spent, "cap": float(cap["cap_usd"]), "behavior": behavior}
            )
            if behavior == "haiku_force":
                model = await self._setting("bridge", "haiku_model", DEFAULT_HAIKU)
            elif behavior == "hard_stop":
                yield SSEEvent(
                    event="error",
                    data=json.dumps({
                        "kind": "budget_hard_stop",
                        "message": f"Cap '{scope}' hit: ${spent:.2f} ≥ ${cap['cap_usd']}.",
                        "scope": scope,
                    }),
                )
                return
        for v in cap_violations:
            yield SSEEvent(event="budget_warning", data=json.dumps(v))

        yield SSEEvent(
            event="model_selected",
            data=json.dumps({"model": model, "reason": intent_data["intent"]}),
        )

        # 7. (F9) Empty-context detection
        total_items = (
            len(sources.handoffs) + len(sources.memories)
            + len(sources.projects) + len(sources.cards)
        )
        if (
            intent_data.get("intent") not in ("general", "save_memory")
            and total_items < LOW_CONTEXT_THRESHOLD
            and not request.confirm_low_context
        ):
            est_in = estimate_tokens(request.message) + 500
            est_out = request.max_tokens or MAX_OUTPUT_TOKENS_DEFAULT
            est_cost = _estimate_turn_cost(model, est_in, est_out)
            yield SSEEvent(
                event="low_context_warning",
                data=json.dumps({
                    "intent": intent_data["intent"],
                    "items_found": total_items,
                    "estimated_cost": round(est_cost, 4),
                    "suggestion": "Run /projects/sync first or query may return 'no data loaded'",
                }),
            )

        # 8. (G2) Token budget — trim sources + history if over budget.
        # force_full_context=true bypasses these checks (caller is opting
        # into a higher-cost call after seeing the empty-context warning).
        ctx_tokens = _sources_token_estimate(sources)
        history_text = "\n".join(
            (m.get("content") or "") if isinstance(m, dict) else "" for m in conv_history
        )
        history_tokens = estimate_tokens(history_text)
        message_tokens = estimate_tokens(request.message)
        total_in = ctx_tokens + history_tokens + message_tokens
        force_full = getattr(request, "force_full_context", False)

        if not force_full and total_in > MAX_CONTEXT_TOKENS:
            sources = _trim_sources(sources)
            ctx_tokens = _sources_token_estimate(sources)
            total_in = ctx_tokens + history_tokens + message_tokens
            yield SSEEvent(
                event="context_truncated",
                data=json.dumps({
                    "reason": "over_token_budget",
                    "limit": MAX_CONTEXT_TOKENS,
                    "after_trim_tokens": total_in,
                    "stage": "soft_trim",
                }),
            )
        if not force_full and total_in > MAX_CONTEXT_TOKENS:
            # Hard truncate to a fixed character cap. Phase 2 reduced this
            # from "leave the leftover budget" (which still oversized when
            # source dump was already small relative to budget) to a flat
            # 25K-char ceiling — keeps the cache-write block under the 50K
            # input-tokens-per-minute Anthropic org cap.
            payload = sources.model_dump()
            blob = json.dumps(payload, default=str)[:HARD_TRUNCATE_CHAR_CAP]
            sources = BridgeSources(
                projects=[{"_truncated_context": blob, "_truncated_at_chars": HARD_TRUNCATE_CHAR_CAP}]
            )
            ctx_tokens = _sources_token_estimate(sources)
            total_in = ctx_tokens + history_tokens + message_tokens
            yield SSEEvent(
                event="context_truncated",
                data=json.dumps({
                    "reason": "hard_char_cap",
                    "char_cap": HARD_TRUNCATE_CHAR_CAP,
                    "after_truncate_tokens": total_in,
                    "stage": "hard_truncate",
                }),
            )

        # 8b. (Phase 2) Preemptive Haiku — large payloads always go to
        # Haiku unless cheap_mode already pinned us there or the user
        # forced Sonnet. Cheaper, faster, less likely to 429.
        if (
            not cheap_mode
            and total_in > PREEMPTIVE_HAIKU_THRESHOLD_TOKENS
            and "haiku" not in (model or "")
            and not (request.force_model and request.force_model.lower().startswith("sonnet"))
        ):
            new_model = await self._setting("bridge", "haiku_model", DEFAULT_HAIKU)
            yield SSEEvent(
                event="model_downgraded",
                data=json.dumps({
                    "from": model, "to": new_model,
                    "reason": "preemptive_haiku_threshold",
                    "tokens_in_estimate": total_in,
                    "threshold": PREEMPTIVE_HAIKU_THRESHOLD_TOKENS,
                }),
            )
            model = new_model

        # 9. (G4) Per-turn cost ceiling — pre-flight check. Cheap mode
        # halves the default output cap.
        per_turn_cap = await self._per_turn_cap()
        out_default = MAX_OUTPUT_TOKENS_DEFAULT // 2 if cheap_mode else MAX_OUTPUT_TOKENS_DEFAULT
        max_out = min(request.max_tokens or out_default, MAX_OUTPUT_TOKENS_HARD_CAP)
        est_cost = _estimate_turn_cost(model, total_in, max_out)
        if per_turn_cap > 0 and est_cost > per_turn_cap:
            yield SSEEvent(
                event="error",
                data=json.dumps({
                    "kind": "per_turn_cap_exceeded",
                    "estimated_cost": round(est_cost, 4),
                    "cap_usd": per_turn_cap,
                    "message": f"Turn would cost ~${est_cost:.4f}, cap is ${per_turn_cap}. Aborting.",
                }),
            )
            return

        # 9b. (Phase 2 / Feature 1+2) Anthropic input-token rate-limit
        # pre-check. If the request would push us over the per-minute hard
        # cap, either queue + retry (when auto_retry is on) or fail
        # immediately. Logs a row in rate_limit_blocks either way.
        tracker = anthropic_input_tokens_tracker()
        allowed, status, msg = tracker.can_consume(total_in)
        if not allowed:
            block_id = await self._log_rate_block(
                api_provider="anthropic",
                requested_tokens=total_in,
                current_usage=tracker.current_usage(),
                limit_value=tracker.HARD_LIMIT,
            )
            if not auto_retry:
                yield SSEEvent(event="error", data=json.dumps({
                    "kind": "rate_limit_block",
                    "provider": "anthropic",
                    "current_usage": tracker.current_usage(),
                    "requested": total_in,
                    "limit": tracker.HARD_LIMIT,
                    "message": msg,
                }))
                await self._resolve_rate_block(block_id, "cancelled")
                return
            eta = tracker.seconds_until_capacity(total_in)
            yield SSEEvent(event="rate_limit_queued", data=json.dumps({
                "provider": "anthropic",
                "wait_seconds": round(eta, 1),
                "current_usage": tracker.current_usage(),
                "requested": total_in,
            }))
            ok, waited = await wait_for_capacity(tracker, total_in)
            if not ok:
                yield SSEEvent(event="error", data=json.dumps({
                    "kind": "rate_limit_timeout",
                    "waited_seconds": round(waited, 1),
                    "message": "Wait would exceed 30s; aborting. Try again in a minute or enable cheap_mode.",
                }))
                await self._resolve_rate_block(block_id, "timeout")
                return
            await self._resolve_rate_block(block_id, "queued_succeeded")
        elif status == "warn":
            yield SSEEvent(event="rate_limit_warn", data=json.dumps({
                "provider": "anthropic",
                "current_usage": tracker.current_usage(),
                "requested": total_in,
                "soft_limit": tracker.SOFT_LIMIT,
            }))
        # Reserve the budget so concurrent turns don't double-spend.
        tracker.consume(total_in)

        # 10. Build system prompt — list-of-blocks form so Anthropic can
        # cache the stable role/voice/capabilities preamble. Cheap mode +
        # explicit prompt_caching_enabled=false fall back to the plain
        # string form (no cache_control, no caching).
        if cache_enabled and not cheap_mode:
            system_prompt: Any = build_cached_system_blocks(
                sources=sources,
                conversation_history=conv_history,
                active_sessions=await self._active_sessions_count(),
                today_spend=await self._today_spend(),
                cache_enabled=True,
            )
        else:
            system_prompt = build_system_prompt(
                sources=sources,
                conversation_history=conv_history,
                active_sessions=await self._active_sessions_count(),
                today_spend=await self._today_spend(),
            )

        # 11. Stream Claude response
        stream_started = time.time()
        messages = [*conv_history, {"role": "user", "content": request.message}]
        full_text = ""
        final_meta: dict[str, Any] = {}
        try:
            async for event in stream_claude_response(
                self.anthropic, model, system_prompt, messages, max_tokens=max_out
            ):
                if event.event == "done":
                    final_meta = json.loads(event.data)
                    full_text = final_meta.get("full_text", "")
                yield event
        except Exception as exc:
            # Anthropic raised mid-stream. Most often a 429 that escaped our
            # pre-check (e.g. concurrent turn already tripped the limit).
            err_text = str(exc)
            is_429 = "rate_limit" in err_text.lower() or "429" in err_text
            if is_429:
                await self._log_rate_block(
                    api_provider="anthropic",
                    requested_tokens=total_in,
                    current_usage=tracker.current_usage(),
                    limit_value=tracker.HARD_LIMIT,
                    resolution="post_call_429",
                )
            yield SSEEvent(event="error", data=json.dumps({
                "kind": "anthropic_error",
                "is_rate_limit": is_429,
                "message": err_text[:400],
            }))
            return
        stream_duration_ms = int((time.time() - stream_started) * 1000)

        # 12. Parse + queue directives
        directives = parse_directives(full_text)
        if directives:
            for directive in directives:
                await self._queue_action(directive)
            yield SSEEvent(
                event="actions_queued",
                data=json.dumps([d.model_dump() for d in directives]),
            )

        # 13. Clean display text
        display_text = strip_directives(full_text)

        # 14. Persist turn
        await self._save_turn(
            conversation_id=conv_id,
            user_message=request.message,
            assistant_message=display_text,
            model=model,
            tokens_in=final_meta.get("tokens_in"),
            tokens_out=final_meta.get("tokens_out"),
            cost=final_meta.get("cost"),
            sources=sources.model_dump(),
            actions_queued=[d.model_dump() for d in directives],
            intent=intent_data["intent"],
            voice_input=request.voice_input,
        )

        # 15. (F10) Cost-log the bridge turn.
        await self._log_cost(
            source_system="bridge",
            project_slug=intent_data.get("project_slug"),
            conversation_id=str(conv_id),
            turn_id=str(uuid4()),
            model=model,
            tokens_in=int(final_meta.get("tokens_in") or 0),
            tokens_out=int(final_meta.get("tokens_out") or 0),
            cost_usd=float(final_meta.get("cost") or 0.0),
            intent=intent_data.get("intent"),
            duration_ms=stream_duration_ms or int((time.time() - turn_started) * 1000),
        )

        # 11. Optional Brain auto-save
        if await self._setting("bridge", "auto_save_conversations", False):
            await self._maybe_save_to_brain(conv_id)

    # ------------------------------------------------------------------
    # Model routing
    # ------------------------------------------------------------------

    async def _choose_model(self, intent: str, force: str | None) -> str:
        # FEATURE 5 — fast intents always go to Haiku unless the caller
        # explicitly forces Sonnet. Status / fact-recall / cost / history
        # don't need reasoning capacity and the price gap is ~4x.
        if intent in FAST_INTENTS:
            if force and force.lower().startswith("sonnet"):
                return await self._setting("bridge", "sonnet_model", DEFAULT_SONNET)
            return await self._setting("bridge", "haiku_model", DEFAULT_HAIKU)
        if force:
            return force
        mode = await self._setting("bridge", "default_model", "auto")
        if mode == "haiku":
            return await self._setting("bridge", "haiku_model", DEFAULT_HAIKU)
        if mode == "sonnet":
            return await self._setting("bridge", "sonnet_model", DEFAULT_SONNET)
        # Auto-route
        if intent in HAIKU_INTENTS:
            return await self._setting("bridge", "haiku_model", DEFAULT_HAIKU)
        if intent in SONNET_INTENTS:
            return await self._setting("bridge", "sonnet_model", DEFAULT_SONNET)
        return await self._setting("bridge", "haiku_model", DEFAULT_HAIKU)

    # ------------------------------------------------------------------
    # Cost intel — logging, cap loading, scope-spend, per-turn cap, compress
    # ------------------------------------------------------------------

    async def _log_cost(
        self,
        *,
        source_system: str,
        cost_usd: float,
        model: str | None = None,
        project_slug: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
        turn_id: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        intent: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        payload = {
            "source_system": source_system,
            "model": model,
            "project_slug": project_slug,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": float(cost_usd or 0.0),
            "intent": intent,
            "duration_ms": duration_ms,
        }
        await self._supabase_run(
            lambda: self.supabase.table(COST_LOG_TABLE).insert(payload).execute()
        )

    async def _load_caps(self) -> list[dict]:
        rows = await self._supabase_run(
            lambda: self.supabase.table(COST_CAPS_TABLE)
            .select("*").eq("enabled", True).execute()
        )
        return getattr(rows, "data", None) or []

    async def _per_turn_cap(self) -> float:
        rows = await self._supabase_run(
            lambda: self.supabase.table(COST_CAPS_TABLE)
            .select("cap_usd,enabled").eq("scope", "bridge_per_turn").limit(1).execute()
        )
        data = getattr(rows, "data", None) or []
        if not data or not data[0].get("enabled"):
            return 0.0
        try:
            return float(data[0].get("cap_usd") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    async def _spend_in_scope(self, scope: str, project_slug: str | None) -> float | None:
        """Aggregate cost_log spend in the named scope. Returns 0.0 if empty."""
        now = datetime.now(timezone.utc)
        if scope == "empire_daily":
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
            project_filter = None
        elif scope == "empire_weekly":
            since = now - timedelta(days=7)
            project_filter = None
        elif scope.startswith("project:") and scope.endswith("_daily"):
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
            project_filter = scope[len("project:") : -len("_daily")]
        elif scope == "bridge_per_turn":
            return None  # not a running aggregate
        else:
            return None

        def _do():
            q = (
                self.supabase.table(COST_LOG_TABLE)
                .select("cost_usd,project_slug")
                .gte("created_at", since.isoformat())
            )
            if project_filter:
                q = q.eq("project_slug", project_filter)
            return q.execute()

        rows = await self._supabase_run(_do)
        data = getattr(rows, "data", None) or []
        return float(sum(float(r.get("cost_usd") or 0) for r in data))

    async def _log_rate_block(
        self,
        *,
        api_provider: str,
        requested_tokens: int,
        current_usage: int,
        limit_value: int,
        queue_depth: int = 0,
        resolution: str | None = None,
    ) -> str | None:
        """Insert a rate_limit_blocks row, return its id or None on failure."""
        payload = {
            "id": str(uuid4()),
            "api_provider": api_provider,
            "requested_tokens": int(requested_tokens),
            "current_usage": int(current_usage),
            "limit_value": int(limit_value),
            "queue_depth": int(queue_depth),
        }
        if resolution:
            payload["resolution"] = resolution
            payload["resolved_at"] = datetime.now(timezone.utc).isoformat()
        await self._supabase_run(
            lambda: self.supabase.table(RATE_LIMIT_BLOCKS_TABLE).insert(payload).execute()
        )
        return payload["id"]

    async def _resolve_rate_block(self, block_id: str | None, resolution: str) -> None:
        if not block_id:
            return
        patch = {
            "resolution": resolution,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._supabase_run(
            lambda: self.supabase.table(RATE_LIMIT_BLOCKS_TABLE)
            .update(patch).eq("id", block_id).execute()
        )

    async def _compress_history(self, conv_id: UUID, history: list[dict]) -> str | None:
        """(F7) Summarize older turns via Haiku. Caches the digest on the
        bridge_conversations row so repeat calls don't re-summarize."""
        existing = await self._supabase_run(
            lambda: self.supabase.table(BRIDGE_CONVERSATIONS_TABLE)
            .select("title").eq("id", str(conv_id)).limit(1).execute()
        )
        rows = getattr(existing, "data", None) or []
        if rows and rows[0].get("title", "").startswith("[digest]"):
            return rows[0]["title"][len("[digest]") :].strip()

        cutoff = max(0, len(history) - MAX_HISTORY_TURNS * 2)
        older = history[:cutoff]
        if not older:
            return None
        snippet = "\n".join(
            f"[{m.get('role','user')}] {(m.get('content') or '')[:400]}"
            for m in older
        )[:6000]
        try:
            haiku_started = time.time()
            resp = await self.anthropic.messages.create(
                model=DEFAULT_HAIKU,
                max_tokens=350,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Summarize this Bridge chat history in 4 bullets. "
                            "Keep concrete facts, decisions, and project slugs. "
                            "Drop pleasantries.\n\n" + snippet
                        ),
                    }
                ],
            )
            digest = resp.content[0].text.strip()
            await self._log_cost(
                source_system="bridge_compress",
                model=DEFAULT_HAIKU,
                conversation_id=str(conv_id),
                tokens_in=getattr(resp.usage, "input_tokens", 0),
                tokens_out=getattr(resp.usage, "output_tokens", 0),
                cost_usd=_estimate_turn_cost(
                    DEFAULT_HAIKU,
                    getattr(resp.usage, "input_tokens", 0),
                    getattr(resp.usage, "output_tokens", 0),
                ),
                duration_ms=int((time.time() - haiku_started) * 1000),
            )
            await self._supabase_run(
                lambda: self.supabase.table(BRIDGE_CONVERSATIONS_TABLE)
                .update({"title": "[digest] " + digest[:1000]})
                .eq("id", str(conv_id))
                .execute()
            )
            return digest
        except Exception as exc:
            logger.debug("compress_history failed: %s", exc)
            return None

    async def _setting(self, namespace: str, key: str, default: Any = None) -> Any:
        if self.settings_cache is None:
            return default
        try:
            result = self.settings_cache.get(namespace, key, default)
            if hasattr(result, "__await__"):
                result = await result
            return result if result is not None else default
        except Exception as exc:
            logger.debug("settings_cache.get(%s,%s) failed: %s", namespace, key, exc)
            return default

    # ------------------------------------------------------------------
    # Supabase persistence
    # ------------------------------------------------------------------

    async def _load_history(self, conv_id: UUID) -> list[dict]:
        """Load prior turns for this conversation as Anthropic-shape messages."""
        rows = await self._supabase_run(
            lambda: self.supabase.table(BRIDGE_TURNS_TABLE)
            .select("user_message,assistant_message,turn_number")
            .eq("conversation_id", str(conv_id))
            .order("turn_number", desc=False)
            .limit(20)
            .execute()
        )
        data = getattr(rows, "data", None) if rows is not None else None
        if not data:
            return []
        history: list[dict] = []
        for row in data:
            if row.get("user_message"):
                history.append({"role": "user", "content": row["user_message"]})
            if row.get("assistant_message"):
                history.append(
                    {"role": "assistant", "content": row["assistant_message"]}
                )
        return history

    async def _save_turn(
        self,
        *,
        conversation_id: UUID,
        user_message: str,
        assistant_message: str,
        model: str,
        tokens_in: int | None,
        tokens_out: int | None,
        cost: float | None,
        sources: dict,
        actions_queued: list[dict],
        intent: str | None,
        voice_input: bool,
    ) -> None:
        # Ensure conversation row exists, then compute turn_number, then insert.
        conv_id_str = str(conversation_id)
        try:
            await self._supabase_run(
                lambda: self.supabase.table(BRIDGE_CONVERSATIONS_TABLE)
                .upsert(
                    {
                        "id": conv_id_str,
                        "started_at": now_iso(),
                        "last_turn_at": now_iso(),
                    },
                    on_conflict="id",
                    ignore_duplicates=True,
                )
                .execute()
            )
        except Exception as exc:
            logger.debug("conversation upsert noop-failed: %s", exc)

        turn_count = await self._count_turns(conversation_id)
        payload = {
            "conversation_id": conv_id_str,
            "turn_number": turn_count + 1,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost,
            "sources_used": sources,
            "actions_queued": actions_queued,
            "intent": intent,
            "voice_input": voice_input,
            "created_at": now_iso(),
        }
        await self._supabase_run(
            lambda: self.supabase.table(BRIDGE_TURNS_TABLE).insert(payload).execute()
        )
        await self._log_history(
            event_type="bridge.turn_created",
            category="bridge",
            action=f"turn {turn_count + 1}",
            details={
                "conversation_id": conv_id_str,
                "intent": intent,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "voice": voice_input,
            },
            cost_usd=cost,
            tokens=(tokens_in or 0) + (tokens_out or 0),
        )

    async def _count_turns(self, conv_id: UUID) -> int:
        rows = await self._supabase_run(
            lambda: self.supabase.table(BRIDGE_TURNS_TABLE)
            .select("id", count="exact")
            .eq("conversation_id", str(conv_id))
            .execute()
        )
        count = getattr(rows, "count", None)
        if count is not None:
            return int(count)
        data = getattr(rows, "data", None) or []
        return len(data)

    async def _queue_action(self, directive) -> None:
        payload = {
            "action_type": directive.action_type,
            "trigger_type": directive.trigger_type,
            "trigger_config": directive.trigger_config,
            "target_project": directive.target_project,
            "target_session": directive.target_session,
            "payload": directive.payload,
            "status": "queued",
            "created_at": now_iso(),
        }
        await self._supabase_run(
            lambda: self.supabase.table(ACTION_QUEUE_TABLE).insert(payload).execute()
        )
        await self._log_history(
            event_type=f"bridge.action_queued",
            category="bridge",
            action=f"queued {directive.action_type}",
            details={
                "project": directive.target_project,
                "session": directive.target_session,
                "trigger": directive.trigger_type,
            },
        )

    async def _log_history(
        self,
        *,
        event_type: str,
        category: str,
        action: str,
        details: dict,
        cost_usd: float | None = None,
        tokens: int | None = None,
        outcome: str = "success",
    ) -> None:
        row = {
            "event_type": event_type,
            "event_category": category,
            "actor": "bridge_chat",
            "action": action,
            "details": details,
            "outcome": outcome,
            "cost_usd": cost_usd,
            "tokens": tokens,
            "created_at": now_iso(),
        }
        try:
            await self._supabase_run(
                lambda: self.supabase.table(HISTORY_LOG_TABLE).insert(row).execute()
            )
        except Exception as exc:
            logger.debug("history_log insert failed: %s", exc)

    async def _supabase_run(self, fn) -> Any:
        try:
            result = fn()
            if hasattr(result, "__await__"):
                result = await result
            return result
        except Exception as exc:
            logger.warning("supabase call failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Live counters used in system prompt
    # ------------------------------------------------------------------

    async def _active_sessions_count(self) -> int | None:
        rows = await self._supabase_run(
            lambda: self.supabase.table("kjcodedeck.live_sessions")
            .select("session_id", count="exact")
            .neq("status", "ended")
            .execute()
        )
        if rows is None:
            return None
        count = getattr(rows, "count", None)
        if count is not None:
            return int(count)
        return len(getattr(rows, "data", None) or [])

    async def _today_spend(self) -> float | None:
        today = datetime.now(timezone.utc).date().isoformat()
        rows = await self._supabase_run(
            lambda: self.supabase.table("kjcodedeck.live_sessions")
            .select("cost_usd")
            .gte("started_at", today)
            .execute()
        )
        if rows is None:
            return None
        data = getattr(rows, "data", None) or []
        return float(sum((r.get("cost_usd") or 0) for r in data))

    # ------------------------------------------------------------------
    # Auto-save to Brain
    # ------------------------------------------------------------------

    async def _maybe_save_to_brain(self, conv_id: UUID) -> None:
        """If the conversation has reached the threshold + isn't saved yet,
        digest it and POST to Brain /memory/save via `brain_save_fn`."""
        if self.brain_save_fn is None:
            return
        turn_count = await self._count_turns(conv_id)
        if turn_count < AUTO_SAVE_TURN_THRESHOLD:
            return
        conv_row = await self._supabase_run(
            lambda: self.supabase.table(BRIDGE_CONVERSATIONS_TABLE)
            .select("saved_to_brain")
            .eq("id", str(conv_id))
            .maybe_single()
            .execute()
        )
        data = getattr(conv_row, "data", None) if conv_row else None
        if data and data.get("saved_to_brain"):
            return

        rows = await self._supabase_run(
            lambda: self.supabase.table(BRIDGE_TURNS_TABLE)
            .select("user_message,assistant_message,turn_number")
            .eq("conversation_id", str(conv_id))
            .order("turn_number", desc=False)
            .execute()
        )
        turns = getattr(rows, "data", None) if rows is not None else None
        if not turns:
            return
        digest = "\n\n".join(
            f"[{t['turn_number']}] USER: {t['user_message']}\n"
            f"ASSISTANT: {t['assistant_message']}"
            for t in turns
        )
        try:
            await self.brain_save_fn(
                {
                    "content": digest,
                    "source": "bridge_chat",
                    "conversation_id": str(conv_id),
                }
            )
        except Exception as exc:
            logger.warning("Brain save failed: %s", exc)
            return

        await self._supabase_run(
            lambda: self.supabase.table(BRIDGE_CONVERSATIONS_TABLE)
            .update({"saved_to_brain": True})
            .eq("id", str(conv_id))
            .execute()
        )
        await self._log_history(
            event_type="bridge.conversation_saved_to_brain",
            category="bridge",
            action="autosave digest → Brain",
            details={"conversation_id": str(conv_id), "turns": turn_count},
        )
