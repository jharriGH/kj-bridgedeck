# bridge-core

Bridge orchestration core for KJ BridgeDeck. Imported by the API layer.

## Exports

```python
from bridge_core import (
    BridgeChatService,   # Streams chat turns with intent routing and context
    VoiceService,        # Whisper STT + Piper TTS
    ActionExecutor,      # Background processor for kjcodedeck.action_queue
    IntentRouter,        # Haiku-based intent classifier
    ContextGatherer,     # Intent-scoped Brain + Supabase context loader
)
```

## Install

```bash
pip install -e ./bridge-core
```

## Layout

- `chat.py` — orchestrator; glues intent → context → prompt → stream → directives
- `intent.py` — `IntentRouter` (Haiku classifier)
- `context.py` — `ContextGatherer` (pulls Brain + Supabase rows by intent)
- `claude_stream.py` — Anthropic streaming wrapper yielding `SSEEvent`
- `directives.py` — parse and strip `[[ACTION: ...]]` directives
- `prompts.py` — `BRIDGE_SYSTEM_PROMPT` template
- `voice.py` — Whisper API + Piper subprocess
- `actions.py` — `ActionExecutor` background loop
- `models.py` — re-exports from `shared.contracts`
- `utils.py` — shared helpers

## Tests

```bash
pip install -e './bridge-core[test]'
pytest bridge-core/tests
```
