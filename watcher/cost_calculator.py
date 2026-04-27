"""
Token -> USD cost math.

Prices in USD per 1M tokens, updated Jan 2026. Keep this list in one place so
we can revisit without grepping the codebase.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_mtok: float
    output_per_mtok: float


_PRICES: dict[str, ModelPricing] = {
    # Claude 4.x family
    "claude-opus-4-7": ModelPricing(15.0, 75.0),
    "claude-opus-4-6": ModelPricing(15.0, 75.0),
    "claude-opus-4-5": ModelPricing(15.0, 75.0),
    "claude-sonnet-4-6": ModelPricing(3.0, 15.0),
    "claude-sonnet-4-5": ModelPricing(3.0, 15.0),
    "claude-haiku-4-5": ModelPricing(1.0, 5.0),
    "claude-haiku-4-5-20251001": ModelPricing(1.0, 5.0),
    # Sensible fallback for unknown model ids
    "__default__": ModelPricing(3.0, 15.0),
}


def pricing_for(model: str | None) -> ModelPricing:
    if not model:
        return _PRICES["__default__"]
    key = model.lower().strip()
    if key in _PRICES:
        return _PRICES[key]
    for prefix, price in _PRICES.items():
        if prefix != "__default__" and key.startswith(prefix):
            return price
    return _PRICES["__default__"]


def calculate_cost(model: str | None, tokens_in: int, tokens_out: int) -> float:
    price = pricing_for(model)
    return round(
        (tokens_in / 1_000_000) * price.input_per_mtok
        + (tokens_out / 1_000_000) * price.output_per_mtok,
        4,
    )
