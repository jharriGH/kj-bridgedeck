"""IntentRouter tests. Uses a fake Anthropic client that returns canned JSON."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from bridge_core.intent import IntentRouter


@dataclass
class _Block:
    text: str


class _Response:
    def __init__(self, text: str):
        self.content = [_Block(text=text)]


class _Messages:
    def __init__(self, canned: str):
        self.canned = canned
        self.last_call: dict[str, Any] | None = None

    async def create(self, **kwargs):
        self.last_call = kwargs
        return _Response(self.canned)


class _FakeAnthropic:
    def __init__(self, canned: str):
        self.messages = _Messages(canned)


@pytest.mark.asyncio
async def test_classify_status_query():
    client = _FakeAnthropic(
        '{"intent": "status_query", "project_slug": "kjwidgetz", "time_range_days": null}'
    )
    router = IntentRouter(client)
    result = await router.classify("What's blocking KJWidgetz?")
    assert result["intent"] == "status_query"
    assert result["project_slug"] == "kjwidgetz"
    assert result["time_range_days"] is None


@pytest.mark.asyncio
async def test_classify_handles_code_fence():
    client = _FakeAnthropic(
        '```json\n{"intent": "fact_recall", "project_slug": null, "time_range_days": null}\n```'
    )
    router = IntentRouter(client)
    result = await router.classify("What did we decide about Twilio?")
    assert result["intent"] == "fact_recall"


@pytest.mark.asyncio
async def test_classify_defaults_on_bad_json():
    client = _FakeAnthropic("not json at all")
    router = IntentRouter(client)
    result = await router.classify("hi")
    assert result == {
        "intent": "general",
        "project_slug": None,
        "time_range_days": None,
    }


@pytest.mark.asyncio
async def test_classify_defaults_on_api_exception():
    class _Broken:
        class messages:
            @staticmethod
            async def create(**_):
                raise RuntimeError("boom")

    router = IntentRouter(_Broken())
    result = await router.classify("anything")
    assert result["intent"] == "general"


@pytest.mark.asyncio
async def test_classify_passes_message_in_prompt():
    client = _FakeAnthropic(
        '{"intent": "next_action", "project_slug": null, "time_range_days": null}'
    )
    router = IntentRouter(client)
    await router.classify("what should I work on next?")
    sent = client.messages.last_call
    assert sent is not None
    content = sent["messages"][0]["content"]
    assert "what should I work on next?" in content
