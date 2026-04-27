"""GET /health — version + downstream health checks."""
from fastapi import APIRouter

from config import settings
from models.responses import HealthResponse
from services.brain_client import BrainClient
from services.supabase_client import ping as supabase_ping
from services.watcher_client import WatcherClient

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    sb_ok = await supabase_ping()
    brain_ok = await BrainClient().health()
    watcher_status = await WatcherClient().health()

    return HealthResponse(
        healthy=sb_ok,
        version=settings.VERSION,
        supabase="ok" if sb_ok else "down",
        brain="ok" if brain_ok else "degraded",
        watcher=watcher_status,
        machine_id=settings.MACHINE_ID,
    )


@router.get("/")
async def root():
    return {
        "service": "kj-bridgedeck-api",
        "version": settings.VERSION,
        "docs": "/docs",
    }
