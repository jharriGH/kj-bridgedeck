"""KJ BridgeDeck — Bridge core.

Chat orchestration, intent routing, voice stack, action executor.
Imported by the FastAPI layer (see api/routes/bridge.py after Bridge-E wiring).
"""
from .chat import BridgeChatService
from .voice import VoiceService
from .actions import ActionExecutor
from .intent import IntentRouter
from .context import ContextGatherer
from .rate_limiter import (
    SlidingWindowRateTracker,
    anthropic_input_tokens_tracker,
    whisper_requests_tracker,
    all_trackers,
)

__all__ = [
    "BridgeChatService",
    "VoiceService",
    "ActionExecutor",
    "IntentRouter",
    "ContextGatherer",
    "SlidingWindowRateTracker",
    "anthropic_input_tokens_tracker",
    "whisper_requests_tracker",
    "all_trackers",
]

__version__ = "0.2.0"
