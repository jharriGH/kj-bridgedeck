"""Bridge — voice-first chat orchestration.

Wires `bridge_core.BridgeChatService` + `VoiceService` into FastAPI:

  POST /bridge/chat              SSE stream of intent → sources → tokens → done
  GET  /bridge/conversations     Supabase list, newest first
  GET  /bridge/conversations/{id}  Single conversation + turn history
  POST /bridge/voice/transcribe  Whisper passthrough
  POST /bridge/voice/synthesize  Piper passthrough (audio/wav)
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from services.supabase_client import run_sync, table  # noqa: F401
from shared.contracts import BridgeChatRequest

logger = logging.getLogger("bridgedeck.api.bridge")

router = APIRouter()


# ---------------------------------------------------------------------------
# Service accessors — the singletons live on app.state (set in main.lifespan).
# ---------------------------------------------------------------------------


def _chat_service(request: Request):
    svc = getattr(request.app.state, "bridge_chat", None)
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "bridge_unavailable",
                "message": "ANTHROPIC_API_KEY not configured — chat disabled.",
            },
        )
    return svc


def _voice_service(request: Request):
    svc = getattr(request.app.state, "voice_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail={"error": "voice_unavailable"})
    return svc


# ---------------------------------------------------------------------------
# POST /bridge/chat — SSE
# ---------------------------------------------------------------------------


@router.post("/chat")
async def chat(request: Request, body: BridgeChatRequest):
    svc = _chat_service(request)

    async def event_stream():
        try:
            async for event in svc.chat(body):
                yield event.format()
        except Exception as exc:  # pragma: no cover — surfaced to client as SSE error
            logger.exception("bridge chat stream error: %s", exc)
            yield f'event: error\ndata: {{"message": "{str(exc).replace(chr(34), "")}"}}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# GET /bridge/conversations
# ---------------------------------------------------------------------------


@router.get("/conversations")
async def list_conversations(limit: int = 50):
    def _do():
        return (
            table("bridge_conversations")
            .select("*")
            .order("last_turn_at", desc=True)
            .limit(min(limit, 200))
            .execute()
        )

    res = await run_sync(_do)
    return {"conversations": res.data or []}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: UUID):
    def _conv():
        return (
            table("bridge_conversations")
            .select("*")
            .eq("id", str(conversation_id))
            .limit(1)
            .execute()
        )

    def _turns():
        return (
            table("bridge_turns")
            .select("*")
            .eq("conversation_id", str(conversation_id))
            .order("turn_number", desc=False)
            .execute()
        )

    conv_res = await run_sync(_conv)
    rows = conv_res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail={"error": "conversation_not_found"})
    turns_res = await run_sync(_turns)
    return {"conversation": rows[0], "turns": turns_res.data or []}


# ---------------------------------------------------------------------------
# POST /bridge/voice/transcribe — Whisper
# ---------------------------------------------------------------------------


class TranscribeRequest(BaseModel):
    audio_base64: str
    mime: str = "audio/webm"


@router.post("/voice/transcribe")
async def transcribe(request: Request, body: TranscribeRequest):
    voice = _voice_service(request)
    try:
        text = await voice.transcribe(body.audio_base64, mime=body.mime)
    except Exception as exc:
        logger.warning("transcribe failed: %s", exc)
        raise HTTPException(status_code=502, detail={"error": "whisper_failed", "message": str(exc)})
    return {"text": text}


# ---------------------------------------------------------------------------
# POST /bridge/voice/synthesize — Piper TTS
# ---------------------------------------------------------------------------


class SynthesizeRequest(BaseModel):
    text: str
    voice: Optional[str] = None


class OutcomeTag(BaseModel):
    outcome: str  # 'useful' | 'partial' | 'wasted' | 'error_refund'


@router.post("/conversations/{conversation_id}/turns/{turn_id}/outcome")
async def tag_turn_outcome(
    conversation_id: str, turn_id: str, body: OutcomeTag
):
    if body.outcome not in ("useful", "partial", "wasted", "error_refund"):
        raise HTTPException(400, "outcome must be useful|partial|wasted|error_refund")

    payload = {
        "turn_id": turn_id,
        "conversation_id": conversation_id,
        "outcome": body.outcome,
    }

    def _do():
        return (
            table("turn_outcomes")
            .upsert(payload, on_conflict="turn_id")
            .execute()
        )
    try:
        res = await run_sync(_do)
    except Exception as exc:
        logger.warning("turn_outcomes upsert failed: %s", exc)
        raise HTTPException(500, f"upsert failed: {exc}")
    rows = res.data or []
    return {"ok": True, "row": rows[0] if rows else payload}


@router.post("/voice/synthesize")
async def synthesize(request: Request, body: SynthesizeRequest):
    voice = _voice_service(request)
    voice_name = body.voice or "en_US-ryan-high"
    try:
        wav_bytes = await voice.synthesize(body.text, voice=voice_name)
    except Exception as exc:
        logger.warning("synthesize failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "piper_unavailable", "message": str(exc)},
        )
    return Response(content=wav_bytes, media_type="audio/wav")
