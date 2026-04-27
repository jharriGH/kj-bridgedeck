"""Anthropic streaming wrapper.

Yields `SSEEvent` objects so the FastAPI layer can forward them as
Server-Sent Events without inspecting Anthropic's internal stream types.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncGenerator

from anthropic import AsyncAnthropic

# Approximate USD per 1M tokens. Update when pricing changes.
COST_TABLE: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"in": 0.80, "out": 4.00},
    "claude-sonnet-4-5": {"in": 3.00, "out": 15.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-opus-4-7": {"in": 15.00, "out": 75.00},
}

DEFAULT_RATES = {"in": 3.00, "out": 15.00}


def calculate_cost(usage, model: str) -> float:
    rates = COST_TABLE.get(model, DEFAULT_RATES)
    tokens_in = getattr(usage, "input_tokens", 0) or 0
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    return (
        tokens_in * rates["in"] / 1_000_000
        + tokens_out * rates["out"] / 1_000_000
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
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = MAX_OUTPUT_TOKENS_DEFAULT,
    temperature: float = 0.7,
) -> AsyncGenerator[SSEEvent, None]:
    """Async generator yielding `SSEEvent`s for each chunk plus a final `done`.

    The `done` event's JSON payload carries `full_text`, token counts, cost,
    stop reason, and model. Callers should capture that to persist the turn."""
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

        yield SSEEvent(
            event="done",
            data=json.dumps(
                {
                    "full_text": full_text,
                    "tokens_in": getattr(final.usage, "input_tokens", 0),
                    "tokens_out": getattr(final.usage, "output_tokens", 0),
                    "cost": cost,
                    "stop_reason": getattr(final, "stop_reason", None),
                    "model": model,
                }
            ),
        )
