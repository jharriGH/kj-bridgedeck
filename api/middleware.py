"""Auth + request logging middleware."""
import logging
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings

logger = logging.getLogger("bridgedeck.api")

OPEN_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/"}


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Require Authorization: Bearer {BRIDGEDECK_ADMIN_KEY} on every route except OPEN_PATHS.

    OPTIONS requests are always allowed through — browser preflights cannot
    carry an Authorization header, so blocking them would make every CORS
    fetch fail. CORSMiddleware (added later, outermost) actually answers the
    preflight; this skip is belt-and-braces for any OPTIONS that slips past."""

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in OPEN_PATHS or path.startswith("/docs") or path.startswith("/openapi"):
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"error": "missing bearer token"}, status_code=401)

        token = auth.removeprefix("Bearer ").strip()
        if token != settings.BRIDGEDECK_ADMIN_KEY:
            return JSONResponse({"error": "invalid admin key"}, status_code=403)

        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
