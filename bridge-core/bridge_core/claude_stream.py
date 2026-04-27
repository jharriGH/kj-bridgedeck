"""Anthropic streaming wrapper.

Yields `SSEEvent` objects so the FastAPI layer can forward them as
Server-Sent Events without inspecting Anthropic's internal stream types.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncGenerator, Union

from anthropic import AsyncAnthropic

# Approximate USD per 1M tokens. Update when pricing changes.
COST_TABLE: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"in": 0.80, "out": 4.00},
    "claude-sonnet-4-5": {"in": 3.00, "out": 15.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-opus-4-7": {"in": 15.00, "out": 75.00},
}

DEFAULT_RATES = {"in": 3.00, "out": 15.00}

# Anthropic prompt-caching multipliers (Anthropic 2026, verified pricing
# documentation as of Jan 2026 cutoff).
CACHE_WRITE_MULTIPLIER = 1.25  # 25% premium on first use
CACHE_READ_MULTIPLIER = 0.10   # 90% discount on subsequent reads


def calculate_cost(usage, model: str) -> float:
    rates = COST_TABLE.get(model, DEFAULT_RATES)
    base_in = rates["in"]
    base_out = rates["out"]
    tokens_in = getattr(usage, "input_tokens", 0) or 0
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (
        tokens_in       * base_in  / 1_000_000
        + cache_write   * base_in  * CACHE_WRITE_MULTIPLIER / 1_000_000
        + cache_read    * base_in  * CACHE_READ_MULTIPLIER  / 1_000_000
        + tokens_out    * base_out / 1_000_000
    )


@dataclass
class SSEEvent:
    event: str
    data: str

    def format(self) -> str:
        return f"event: {self.event}\ndata: {self.data}\n\n"


MAX_OUTPUT_TOKENS_DEFAULT = 2048
MAX_OUTPUT_TOKENS_HARD_CAP = 8192


async def stream_claude_response(
    client: AsyncAnthropic,
    model: str,
    system_prompt: Union[str, list[dict]],
    messages: list[dict],
    max_tokens: int = MAX_OUTPUT_TOKENS_DEFAULT,
    temperature: float = 0.7,
) -> AsyncGenerator[SSEEvent, None]:
    """Async generator yielding `SSEEvent`s for each chunk plus a final `done`.

    `system_prompt` can be either a plain string or a list of text blocks
    (each optionally carrying ``cache_control``). The list form unlocks
    Anthropic prompt caching — see prompts.build_cached_system_blocks.

    The `done` event's JSON payload carries `full_text`, token counts, cost,
    stop reason, and model — plus `cache_creation_tokens` /
    `cache_read_tokens` so callers can audit cache hit rate."""
    full_text = ""
    async with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            full_text += text
            yield SSEEvent(event="message_delta", data=json.dumps({"text": text}))

        final = await stream.get_final_message()
        cost = calculate_cost(final.usage, model)
        usage = final.usage

        yield SSEEvent(
            event="done",
            data=json.dumps(
                {
                    "full_text": full_text,
                    "tokens_in": getattr(usage, "input_tokens", 0),
                    "tokens_out": getattr(usage, "output_tokens", 0),
                    "cache_creation_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
                    "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
                    "cost": cost,
                    "stop_reason": getattr(final, "stop_reason", None),
                    "model": model,
                }
            ),
        )
