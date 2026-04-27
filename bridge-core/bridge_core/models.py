"""Re-exports of shared Pydantic contracts.

Avoids scattering `from shared.contracts import ...` lines across bridge_core
modules. Consumers can pick models from either location.
"""
from shared.contracts import (
    ActionDirective,
    ActionStatus,
    ActionType,
    BridgeChatRequest,
    BridgeConversation,
    BridgeSources,
    BridgeTurn,
    HistoryEvent,
    QueryIntent,
    QueuedAction,
    SessionHandoff,
    SessionLaunchRequest,
    SessionMessageRequest,
    TriggerType,
)

__all__ = [
    "ActionDirective",
    "ActionStatus",
    "ActionType",
    "BridgeChatRequest",
    "BridgeConversation",
    "BridgeSources",
    "BridgeTurn",
    "HistoryEvent",
    "QueryIntent",
    "QueuedAction",
    "SessionHandoff",
    "SessionLaunchRequest",
    "SessionMessageRequest",
    "TriggerType",
]
