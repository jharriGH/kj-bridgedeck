"""Empire pricing reference for cost calculation.

Numbers are USD per 1M tokens unless otherwise noted. Update this file
when Anthropic / OpenAI publish new rates — every KJE product that
imports kje_cost_logger picks up the new prices on next deploy.

Cache pricing follows Anthropic 2026 multipliers:
  - cache_write = 1.25× input rate
  - cache_read  = 0.10× input rate
The numbers below are pre-multiplied so callers don't need to apply them.
"""
from __future__ import annotations


ANTHROPIC_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
        "cache_write": 1.00,   # 1.25× input
        "cache_read": 0.08,    # 0.10× input
    },
    "claude-sonnet-4-5-20250514": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-sonnet-4-5": {  # alias
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-opus-4-7-20260101": {
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,
        "cache_read": 1.50,
    },
    "claude-opus-4-7": {  # alias
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,
        "cache_read": 1.50,
    },
}

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
) -> float:
    """Compute USD cost for an Anthropic call. Returns 0.0 for unknown
    models — callers should log a warning if cost stays at 0."""
    rates = ANTHROPIC_PRICING.get(model)
    if not rates:
        return 0.0
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
) -> float:
    """Compute USD cost for an OpenAI call. Whisper bills per-minute;
    everything else bills per-token. Returns 0.0 for unknown models."""
    rates = OPENAI_PRICING.get(model)
    if not rates:
        return 0.0
    if "per_minute" in rates:
        return round(audio_minutes * rates["per_minute"], 6)
    return round(
        (tokens_in  / 1_000_000) * rates.get("input", 0.0)
        + (tokens_out / 1_000_000) * rates.get("output", 0.0),
        6,
    )
