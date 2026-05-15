"""/hosting/* — provider-scoped hosting spend tiles.

Each chunk of the hosting-billing rollout adds one provider here. Auth is
the global AdminAuthMiddleware, same as every other authenticated route.

Chunk 1 (Render) shipped at /cost/hosting under the cost router for
historical reasons; that endpoint is unchanged. New providers live here
under /hosting/{provider}/spend so the namespace is consistent going
forward (Twilio lands in chunk 3).
"""
from __future__ import annotations

from fastapi import APIRouter

from services.cloudflare_billing import get_cloudflare_spend

router = APIRouter()


@router.get("/cloudflare/spend")
async def cloudflare_spend() -> dict:
    """Best-effort monthly Cloudflare spend. Cached 1h. Returns a stable
    shape with ``configured: false`` if CF_API_TOKEN / CF_ACCOUNT_ID
    aren't set, so the UI tile renders gracefully."""
    return await get_cloudflare_spend()
