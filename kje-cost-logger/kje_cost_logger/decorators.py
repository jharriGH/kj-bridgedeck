"""Decorator helpers for low-friction Anthropic call logging.

Usage:

    from kje_cost_logger import CostLogger, track_cost
    logger = CostLogger(...)

    @track_cost(logger, intent="lead_qualification")
    async def qualify_lead(lead):
        return await anthropic.messages.create(model="claude-sonnet-4-5", ...)

The decorator measures wall time, extracts model + usage from the
returned response, and POSTs to BridgeDeck. The wrapped function's
return value is passed through unchanged.
"""
from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable, Optional


def track_cost(
    logger: Any,
    intent: Optional[str] = None,
    model_extractor: Optional[Callable[[Any], str]] = None,
    metadata_extractor: Optional[Callable[[Any], dict]] = None,
):
    """Decorator that auto-logs cost from anthropic SDK calls.

    `model_extractor` is an optional callable that pulls the model id
    from the wrapped function's response. Defaults to
    ``getattr(response, "model", None)``."""
    def decorator(fn: Callable):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            start = time.time()
            response = await fn(*args, **kwargs)
            duration_ms = int((time.time() - start) * 1000)

            model = model_extractor(response) if model_extractor else getattr(response, "model", None)
            if model and hasattr(response, "usage"):
                meta = metadata_extractor(response) if metadata_extractor else None
                try:
                    await logger.log_anthropic_call(
                        response=response,
                        model=model,
                        intent=intent,
                        duration_ms=duration_ms,
                        metadata=meta,
                    )
                except Exception:
                    # Decorator must NEVER swallow the wrapped function's
                    # return value — but it also must not propagate logging
                    # exceptions. CostLogger has its own fail_silently flag;
                    # this is a backstop.
                    pass
            return response
        return wrapper
    return decorator
