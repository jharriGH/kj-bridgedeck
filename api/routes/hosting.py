"""/hosting/* — provider-scoped hosting spend tiles.

Each chunk of the hosting-billing rollout adds one provider here. Auth is
the global AdminAuthMiddleware, same as every other authenticated route.

Chunk 1 (Render) shipped at /cost/hosting under the cost router. That
endpoint is preserved for back-compat; the canonical path going forward
is /hosting/render/spend (added in chunk 3 as an alias that delegates to
the same get_render_spend()).
"""
from __future__ import annotations

from fastapi import APIRouter

from services.cloudflare_billing import get_cloudflare_spend
from services.render_billing import get_render_spend
from services.twilio_billing import get_twilio_spend

router = APIRouter()


@router.get("/render/spend")
async def render_spend() -> dict:
    """Render hosting spend (plan-rate estimate). Alias for /cost/hosting —
    delegates to the same get_render_spend() so both URLs stay in sync."""
    return await get_render_spend()


@router.get("/cloudflare/spend")
async def cloudflare_spend() -> dict:
    """Best-effort monthly Cloudflare spend. Cached 1h. Returns a stable
    shape with ``configured: false`` if CF_API_TOKEN / CF_ACCOUNT_ID
    aren't set, so the UI tile renders gracefully."""
    return await get_cloudflare_spend()


@router.get("/twilio/spend")
async def twilio_spend() -> dict:
    """Month-to-date Twilio spend from Usage Records (billed truth, not an
    estimate). Cached 1h. Returns a stable shape with ``configured: false``
    if TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN aren't set."""
    return await get_twilio_spend()
