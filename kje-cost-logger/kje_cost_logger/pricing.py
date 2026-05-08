"""Empire pricing reference for cost calculation.

Numbers are USD per 1M tokens unless otherwise noted. Update this file
when Anthropic / OpenAI publish new rates — every KJE product that
imports kje_cost_logger picks up the new prices on next deploy.

Cache pricing follows Anthropic 2026 multipliers:
  - cache_write = 1.25× input rate
  - cache_read  = 0.10× input rate
The numbers below are pre-multiplied so callers don't need to apply them.

Model name resolution: Anthropic publishes both bare aliases
(``claude-sonnet-4-5``) and dated snapshots (``claude-sonnet-4-5-20250929``)
that point to the same model with identical pricing. This module
normalizes any ``-YYYYMMDD`` suffix back to the bare alias before lookup,
so new dated snapshots don't silently fall through to the unknown-model
sentinel. Add an explicit dated entry when you want to pin a different
rate for that snapshot.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Sentinel returned when a model isn't found. Small enough not to skew
# totals but non-zero so /cost/coverage flags the source as instrumented
# and the missing-model warning surfaces in logs immediately.
UNKNOWN_MODEL_SENTINEL = 0.000001

_DATED_SUFFIX = re.compile(r"-(\d{8})$")


_SONNET_4_5 = {
    "input": 3.00,
    "output": 15.00,
    "cache_write": 3.75,    # 1.25× input
    "cache_read": 0.30,     # 0.10× input
}

_OPUS_4_7 = {
    "input": 15.00,
    "output": 75.00,
    "cache_write": 18.75,
    "cache_read": 1.50,
}

ANTHROPIC_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
        "cache_write": 1.00,   # 1.25× input
        "cache_read": 0.08,    # 0.10× input
    },
    "claude-haiku-4-5": {       # bare alias
        "input": 0.80,
        "output": 4.00,
        "cache_write": 1.00,
        "cache_read": 0.08,
    },
    "claude-sonnet-4-5":          _SONNET_4_5,   # bare alias
    "claude-sonnet-4-5-20250514": _SONNET_4_5,   # original launch snapshot
    "claude-sonnet-4-5-20250929": _SONNET_4_5,   # 2026-Q1 snapshot — was the silent-zero culprit
    "claude-sonnet-4-6":          _SONNET_4_5,
    "claude-opus-4-7":            _OPUS_4_7,
    "claude-opus-4-7-20260101":   _OPUS_4_7,
}


def _resolve_anthropic_model(model: str) -> dict[str, float] | None:
    """Look up an Anthropic model in ANTHROPIC_PRICING with dated-alias fallback.

    Tries the literal model string first; if that misses and the string
    ends in ``-YYYYMMDD``, retries with the suffix stripped. Returns the
    rates dict or None when both lookups fail."""
    rates = ANTHROPIC_PRICING.get(model)
    if rates is not None:
        return rates
    bare = _DATED_SUFFIX.sub("", model)
    if bare != model:
        return ANTHROPIC_PRICING.get(bare)
    return None

OPENAI_PRICING: dict[str, dict[str, float]] = {
    # whisper-1 is per-minute, not per-token.
    "whisper-1": {"per_minute": 0.006},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "text-embedding-3-small": {"input": 0.02},
    "text-embedding-3-large": {"input": 0.13},
}


def calc_anthropic_cost(
    model: str,
    tokens_in: int,
    tokens_out: int,
    cache_read: int = 0,
    cache_write: int = 0,
    source_system: str | None = None,
) -> float:
    """Compute USD cost for an Anthropic call.

    Returns ``UNKNOWN_MODEL_SENTINEL`` (a tiny non-zero value) for
    unknown models AND logs a warning so the gap surfaces immediately
    instead of accumulating silent zeros."""
    rates = _resolve_anthropic_model(model)
    if rates is None:
        logger.warning(
            "kje_cost_logger: unknown Anthropic model %r (source_system=%r) — "
            "returning sentinel %.6f. Add it to pricing.ANTHROPIC_PRICING.",
            model, source_system, UNKNOWN_MODEL_SENTINEL,
        )
        return UNKNOWN_MODEL_SENTINEL
    return round(
        (tokens_in   / 1_000_000) * rates["input"]
        + (tokens_out / 1_000_000) * rates["output"]
        + (cache_read  / 1_000_000) * rates["cache_read"]
        + (cache_write / 1_000_000) * rates["cache_write"],
        6,
    )


def calc_openai_cost(
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    audio_minutes: float = 0.0,
    source_system: str | None = None,
) -> float:
    """Compute USD cost for an OpenAI call. Whisper bills per-minute;
    everything else bills per-token.

    Returns ``UNKNOWN_MODEL_SENTINEL`` + logs a warning for unknown models."""
    rates = OPENAI_PRICING.get(model)
    if rates is None:
        logger.warning(
            "kje_cost_logger: unknown OpenAI model %r (source_system=%r) — "
            "returning sentinel %.6f. Add it to pricing.OPENAI_PRICING.",
            model, source_system, UNKNOWN_MODEL_SENTINEL,
        )
        return UNKNOWN_MODEL_SENTINEL
    if "per_minute" in rates:
        return round(audio_minutes * rates["per_minute"], 6)
    return round(
        (tokens_in  / 1_000_000) * rates.get("input", 0.0)
        + (tokens_out / 1_000_000) * rates.get("output", 0.0),
        6,
    )
