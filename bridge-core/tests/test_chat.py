"""BridgeChatService smoke tests with fakes for every dependency."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from shared.contracts import BridgeChatRequest

from bridge_core.chat import BridgeChatService
from bridge_core.claude_stream import SSEEvent


@dataclass
class _Block:
    text: str


class _StreamContext:
    """Async context manager mimicking anthropic.messages.stream."""

    def __init__(self, chunks, tokens_in=50, tokens_out=120):
        self._chunks = chunks
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    @property
    def text_stream(self):
        async def gen():
            for c in self._chunks:
                yield c

        return gen()

    async def get_final_message(self):
        @dataclass
        class _Usage:
            input_tokens: int
            output_tokens: int

        @dataclass
        class _Final:
            usage: _Usage
            stop_reason: str = "end_turn"

        return _Final(_Usage(self._tokens_in, self._tokens_out))


class _FakeMessages:
    def __init__(self, intent_json: str, chunks):
        self._intent_json = intent_json
        self._chunks = chunks

    async def create(self, **_):
        return type("R", (), {"content": [_Block(text=self._intent_json)]})

    def stream(self, **_):
        return _StreamContext(self._chunks)


class _FakeAnthropic:
    def __init__(self, intent_json: str, chunks):
        self.messages = _FakeMessages(intent_json, chunks)


class _QueryBuilder:
    """Fluent query builder mock — every chainable method returns self."""

    def __init__(self, table_name: str, inserts: list, data=None):
        self.table_name = table_name
        self._inserts = inserts
        self._data = data or []
        self._count = 0

    def select(self, *args, **kwargs):
        return self

    def insert(self, payload):
        self._inserts.append({"table": self.table_name, "payload": payload})
        return self

    def update(self, payload):
        self._inserts.append({"table": self.table_name, "update": payload})
        return self

    def upsert(self, payload, **kwargs):
        self._inserts.append({"table": self.table_name, "upsert": payload})
        return self

    def eq(self, *a, **kw):
        return self

    def neq(self, *a, **kw):
        return self

    def gte(self, *a, **kw):
        return self

    def lte(self, *a, **kw):
        return self

    def order(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        class _Res:
            def __init__(self, data, count):
                self.data = data
                self.count = count

        return _Res(self._data, self._count)


class _FakeSupabase:
    def __init__(self):
        self.inserts: list = []

    def table(self, name: str):
        return _QueryBuilder(name, self.inserts)


class _FakeSettings:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, namespace, key, default=None):
        return self.values.get((namespace, key), default)


@pytest.mark.asyncio
async def test_chat_streams_and_persists(monkeypatch):
    intent_json = (
        '{"intent": "general", "project_slug": null, "time_range_days": null}'
    )
    chunks = ["Hello Jim. ", "The bridge is online."]
    anthropic_client = _FakeAnthropic(intent_json, chunks)
    supabase = _FakeSupabase()

    # Stub out context gathering to avoid HTTP calls.
    async def _empty_gather(*args, **kwargs):
        from shared.contracts import BridgeSources

        return BridgeSources()

    service = BridgeChatService(
        anthropic_client=anthropic_client,
        brain_url="http://brain.local",
        brain_key="test",
        supabase_client=supabase,
        settings_cache=_FakeSettings({("bridge", "default_model"): "haiku"}),
    )
    service.context_gatherer.gather = _empty_gather  # type: ignore[assignment]

    req = BridgeChatRequest(message="hi", stream=True)
    events = []
    async for ev in service.chat(req):
        events.append(ev)

    event_names = [e.event for e in events]
    assert "intent" in event_names
    assert "sources" in event_names
    assert "model_selected" in event_names
    assert "message_delta" in event_names
    assert "done" in event_names

    done = next(e for e in events if e.event == "done")
    payload = json.loads(done.data)
    assert payload["full_text"] == "Hello Jim. The bridge is online."
    assert payload["tokens_in"] == 50
    assert payload["tokens_out"] == 120
    # A turn row should have been inserted into bridge_turns.
    assert any(
        i.get("payload") and i["table"] == "kjcodedeck.bridge_turns"
        for i in supabase.inserts
    )


@pytest.mark.asyncio
async def test_chat_queues_directive(monkeypatch):
    intent_json = (
        '{"intent": "save_memory", "project_slug": null, "time_range_days": null}'
    )
    chunks = [
        'Saving. [[ACTION: save_memory content="remember X" tags=["kje"]]]'
    ]
    anthropic_client = _FakeAnthropic(intent_json, chunks)
    supabase = _FakeSupabase()

    async def _empty_gather(*args, **kwargs):
        from shared.contracts import BridgeSources

        return BridgeSources()

    service = BridgeChatService(
        anthropic_client=anthropic_client,
        brain_url="http://brain.local",
        brain_key="test",
        supabase_client=supabase,
        settings_cache=_FakeSettings(),
    )
    service.context_gatherer.gather = _empty_gather  # type: ignore[assignment]

    req = BridgeChatRequest(message="remember X", stream=True)
    events = []
    async for ev in service.chat(req):
        events.append(ev)

    # actions_queued event should fire with one directive
    queued = [e for e in events if e.event == "actions_queued"]
    assert len(queued) == 1
    payload = json.loads(queued[0].data)
    assert len(payload) == 1
    # save_memory aliases to brain_query at the contract layer
    assert payload[0]["action_type"] == "brain_query"
    assert payload[0]["payload"]["operation"] == "save"
    # action_queue insert must exist
    assert any(i["table"] == "kjcodedeck.action_queue" for i in supabase.inserts)
