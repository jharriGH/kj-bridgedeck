"""CostLogger — async client for POSTing rows to BridgeDeck /cost/ingest.

Designed to fail silently by default so cost logging never breaks the
hot path. Set ``fail_silently=False`` in tests/CI when you want noisy
failure modes.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .pricing import calc_anthropic_cost, calc_openai_cost

logger = logging.getLogger(__name__)


class CostLogger:
    def __init__(
        self,
        bridgedeck_url: str,
        api_key: str,
        source_system: str,
        project_slug: Optional[str] = None,
        fail_silently: bool = True,
        timeout_seconds: float = 5.0,
    ):
        if not bridgedeck_url:
            raise ValueError("bridgedeck_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        if not source_system:
            raise ValueError("source_system is required")
        self.url = bridgedeck_url.rstrip("/") + "/cost/ingest"
        self.api_key = api_key
        self.source_system = source_system
        self.project_slug = project_slug
        self.fail_silently = fail_silently
        self.timeout = timeout_seconds

    # ------------------------------------------------------------------
    # Anthropic — preferred path. Pass the response object directly.
    # ------------------------------------------------------------------

    async def log_anthropic_call(
        self,
        response: Any,
        model: str,
        intent: Optional[str] = None,
        duration_ms: Optional[int] = None,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        usage = getattr(response, "usage", None)
        if usage is None:
            return await self._post({"source_system": self.source_system, "model": model, "cost_usd": 0.0,
                                     "intent": intent, "metadata": {"warning": "no_usage_on_response"}})

        tokens_in   = int(getattr(usage, "input_tokens", 0) or 0)
        tokens_out  = int(getattr(usage, "output_tokens", 0) or 0)
        cache_read  = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)

        cost = calc_anthropic_cost(model, tokens_in, tokens_out, cache_read, cache_write)

        return await self._post({
            "source_system": self.source_system,
            "project_slug": self.project_slug,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "cost_usd": cost,
            "intent": intent,
            "duration_ms": duration_ms,
            "metadata": metadata,
        })

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------

    async def log_openai_call(
        self,
        response: Any,
        model: str,
        intent: Optional[str] = None,
        duration_ms: Optional[int] = None,
        audio_minutes: float = 0.0,
        session_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        usage = getattr(response, "usage", None)
        tokens_in  = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0

        cost = calc_openai_cost(model, tokens_in, tokens_out, audio_minutes)

        meta = {"audio_minutes": audio_minutes} if audio_minutes else {}
        if metadata:
            meta.update(metadata)

        return await self._post({
            "source_system": self.source_system,
            "project_slug": self.project_slug,
            "session_id": session_id,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost,
            "intent": intent,
            "duration_ms": duration_ms,
            "metadata": meta or None,
        })

    # ------------------------------------------------------------------
    # Manual — pass any combination of fields. Useful for non-Anthropic /
    # non-OpenAI providers (Vapi, ElevenLabs, etc).
    # ------------------------------------------------------------------

    async def log_manual(self, **kwargs) -> dict:
        payload = {
            "source_system": self.source_system,
            "project_slug": self.project_slug,
        }
        payload.update(kwargs)
        return await self._post(payload)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _post(self, payload: dict) -> dict:
        # Drop None values so the server-side pydantic model doesn't have
        # to deal with explicit nulls.
        payload = {k: v for k, v in payload.items() if v is not None}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(
                    self.url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                if r.status_code == 200:
                    return r.json()
                msg = f"BridgeDeck cost ingest failed: {r.status_code} {r.text[:200]}"
                if self.fail_silently:
                    logger.warning(msg)
                    return {"logged": False, "error": msg}
                raise RuntimeError(msg)
        except httpx.HTTPError as exc:
            msg = f"BridgeDeck cost ingest network error: {exc}"
            if self.fail_silently:
                logger.debug(msg)
                return {"logged": False, "error": msg}
            raise
