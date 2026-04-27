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
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import UUID, uuid4

from anthropic import AsyncAnthropic

from shared.contracts import BridgeChatRequest, BridgeSources

from .claude_stream import SSEEvent, stream_claude_response
from .context import ContextGatherer
from .directives import parse_directives, strip_directives
from .intent import IntentRouter
from .prompts import build_system_prompt
from .utils import now_iso
from .voice import VoiceService

logger = logging.getLogger(__name__)

DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
DEFAULT_SONNET = "claude-sonnet-4-5"
HAIKU_INTENTS = {"status_query", "fact_recall", "cost_query", "save_memory", "general"}
SONNET_INTENTS = {"next_action", "session_history", "empire_summary", "launch_session"}

BRIDGE_CONVERSATIONS_TABLE = "kjcodedeck.bridge_conversations"
BRIDGE_TURNS_TABLE = "kjcodedeck.bridge_turns"
ACTION_QUEUE_TABLE = "kjcodedeck.action_queue"
HISTORY_LOG_TABLE = "kjcodedeck.history_log"
AUTO_SAVE_TURN_THRESHOLD = 6


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
        # 1. Voice input → transcribe
        if request.voice_input and request.audio_base64:
            transcript = await self.voice.transcribe(request.audio_base64)
            request.message = transcript
            yield SSEEvent(
                event="transcript", data=json.dumps({"text": transcript})
            )

        # 2. Load conversation state
        conv_id = request.conversation_id or uuid4()
        conv_history = await self._load_history(conv_id)

        # 3. Classify intent
        intent_data = await self.intent_router.classify(request.message)
        yield SSEEvent(event="intent", data=json.dumps(intent_data))

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

        # 5. Choose model
        model = await self._choose_model(intent_data["intent"], request.force_model)
        yield SSEEvent(
            event="model_selected",
            data=json.dumps({"model": model, "reason": intent_data["intent"]}),
        )

        # 6. Build system prompt
        system_prompt = build_system_prompt(
            sources=sources,
            conversation_history=conv_history,
            active_sessions=await self._active_sessions_count(),
            today_spend=await self._today_spend(),
        )

        # 7. Stream Claude response
        messages = [*conv_history, {"role": "user", "content": request.message}]
        full_text = ""
        final_meta: dict[str, Any] = {}
        async for event in stream_claude_response(
            self.anthropic, model, system_prompt, messages
        ):
            if event.event == "done":
                final_meta = json.loads(event.data)
                full_text = final_meta.get("full_text", "")
            yield event

        # 8. Parse + queue directives
        directives = parse_directives(full_text)
        if directives:
            for directive in directives:
                await self._queue_action(directive)
            yield SSEEvent(
                event="actions_queued",
                data=json.dumps([d.model_dump() for d in directives]),
            )

        # 9. Clean display text
        display_text = strip_directives(full_text)

        # 10. Persist turn
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

        # 11. Optional Brain auto-save
        if await self._setting("bridge", "auto_save_conversations", False):
            await self._maybe_save_to_brain(conv_id)

    # ------------------------------------------------------------------
    # Model routing
    # ------------------------------------------------------------------

    async def _choose_model(self, intent: str, force: str | None) -> str:
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
