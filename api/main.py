"""KJ BridgeDeck API — FastAPI service on Render."""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure repo root is on sys.path so `import shared.contracts` works in both
# `cd api && uvicorn main:app` and Docker layouts.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from middleware import AdminAuthMiddleware, RequestLoggingMiddleware
from routes import (
    action_queue,
    auto_approve,
    bridge,
    cost,
    handoffs,
    health,
    history,
    notes,
    projects,
    sessions,
)
from routes import settings as settings_routes
from routes import stats
from services import history_logger as history_log
from services.brain_client import BrainClient
from services.settings_cache import SettingsCache
from services.supabase_client import get_supabase
from services.watcher_client import WatcherClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bridgedeck.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting bridgedeck api v%s", settings.VERSION)
    await SettingsCache.initialize()

    # Bridge core (chat + voice + action executor). Optional — if anthropic
    # isn't installed or no key is set, the routes return 503 with guidance.
    app.state.bridge_chat = None
    app.state.voice_service = None
    app.state.action_executor = None
    app.state.action_executor_task = None

    try:
        from anthropic import AsyncAnthropic
        from bridge_core import (
            ActionExecutor,
            BridgeChatService,
            VoiceService,
        )
    except ImportError as exc:
        logger.warning("bridge-core not installed (%s) — /bridge routes will 503", exc)
    else:
        # Voice service — works even without Piper (transcribe will refuse
        # without OPENAI_API_KEY; synthesize requires PIPER paths).
        import os
        voice = VoiceService(
            openai_key=settings.OPENAI_API_KEY,
            piper_binary=os.environ.get("PIPER_BINARY_PATH") or None,
            piper_models_dir=_resolve_models_dir(os.environ.get("PIPER_MODEL_PATH")),
        )
        app.state.voice_service = voice

        if settings.ANTHROPIC_API_KEY:
            sb = get_supabase()
            anthropic_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            brain = BrainClient()

            async def _brain_save(payload: dict) -> dict:
                return await brain._request("POST", "/memory/save", json=payload)

            sb_shim = _SchemaQualifiedSupabase(sb)
            app.state.bridge_chat = BridgeChatService(
                anthropic_client=anthropic_client,
                brain_url=settings.BRAIN_API_URL,
                brain_key=settings.BRAIN_KEY,
                supabase_client=sb_shim,
                voice_service=voice,
                settings_cache=SettingsCache,
                brain_save_fn=_brain_save,
            )

            executor = ActionExecutor(
                supabase_client=sb_shim,
                watcher_client=WatcherClient(),
                brain_client=brain,
                history_logger=history_log,
                interval=15,
            )
            app.state.action_executor = executor
            app.state.action_executor_task = asyncio.create_task(executor.start())
            logger.info("ActionExecutor started (interval=15s)")
        else:
            logger.warning("ANTHROPIC_API_KEY not set — bridge chat + executor disabled")

    try:
        yield
    finally:
        executor = app.state.action_executor
        task = app.state.action_executor_task
        if executor is not None:
            await executor.stop()
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        await SettingsCache.close()
        logger.info("shutdown complete")


def _resolve_models_dir(piper_model_env: str | None) -> str | None:
    """install_piper.ps1 writes the .onnx file path to PIPER_MODEL_PATH;
    VoiceService wants the *directory*. Accept either."""
    if not piper_model_env:
        return None
    p = Path(piper_model_env)
    return str(p.parent if p.suffix == ".onnx" else p)


class _SchemaQualifiedSupabase:
    """Adapter so bridge_core can pass schema-qualified table names like
    'kjcodedeck.bridge_conversations' into supabase-py's `.table()`.

    bridge_core was authored to a hypothetical schema-aware client; supabase-py
    needs the schema set on the postgrest builder instead. This shim splits
    'schema.table' and forwards to `client.postgrest.schema(s).from_(t)`."""

    def __init__(self, client):
        self._client = client

    def table(self, qualified_name: str):
        if "." in qualified_name:
            schema, name = qualified_name.split(".", 1)
            return self._client.postgrest.schema(schema).from_(name)
        return self._client.table(qualified_name)


app = FastAPI(
    title="KJ BridgeDeck API",
    version=settings.VERSION,
    description="Empire command interface backend",
    lifespan=lifespan,
)

# Middleware order matters. Starlette processes middleware OUTERMOST FIRST,
# and `add_middleware` PREPENDS to that chain — i.e. the LAST .add_middleware
# call wraps the OUTERMOST. So to make CORS the outermost (so it can answer
# OPTIONS preflights and attach Access-Control-Allow-Origin to ANY response,
# including 401s from auth), it must be added LAST.
app.add_middleware(AdminAuthMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # MUST be False with allow_origins=["*"] per CORS spec
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

app.include_router(health.router, tags=["health"])
app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
app.include_router(handoffs.router, prefix="/handoffs", tags=["handoffs"])
app.include_router(notes.router, prefix="/notes", tags=["notes"])
app.include_router(history.router, prefix="/history", tags=["history"])
app.include_router(settings_routes.router, prefix="/settings", tags=["settings"])
app.include_router(auto_approve.router, prefix="/auto-approve", tags=["auto_approve"])
app.include_router(action_queue.router, prefix="/actions", tags=["actions"])
app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(bridge.router, prefix="/bridge", tags=["bridge"])
app.include_router(stats.router, prefix="/stats", tags=["stats"])
app.include_router(cost.router, prefix="/cost", tags=["cost"])
