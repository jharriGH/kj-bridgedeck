"""
KJ BridgeDeck — Shared Pydantic contracts.
ALL BRIDGE AGENTS IMPORT FROM THIS FILE.
Do not modify without coordinating across all components.
"""
from datetime import datetime
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field
from uuid import UUID


# ============================================================================
# SESSION CONTRACTS
# ============================================================================

SessionStatus = Literal["processing", "waiting", "needs_input", "idle", "ended"]


class LiveSession(BaseModel):
    session_id: str
    project_slug: str
    machine_id: str
    pid: Optional[int] = None
    cwd: Optional[str] = None
    terminal_app: Optional[str] = None
    window_title: Optional[str] = None
    tmux_session: Optional[str] = None
    status: SessionStatus
    model: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    started_at: datetime
    last_activity: datetime
    jsonl_path: Optional[str] = None
    needs_input_msg: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class SessionLaunchRequest(BaseModel):
    project_slug: str
    initial_prompt: Optional[str] = None
    working_directory: Optional[str] = None


class SessionMessageRequest(BaseModel):
    text: str
    session_id: str


# ============================================================================
# HANDOFF CONTRACTS — matches Brain v1.4.0 exactly
# ============================================================================

HandoffStatus = Literal["completed", "aborted", "partial"]


class SessionHandoff(BaseModel):
    """Matches POST /codedeck/handoff payload on Brain API v1.4.0."""
    project_slug: str
    summary: str
    decisions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    next_action: Optional[str] = None
    token_cost: float
    session_id: str
    confidence: float = Field(ge=0, le=1)
    agent: Literal["codedeck_watcher"] = "codedeck_watcher"
    status: HandoffStatus


class BrainHandoffResponse(BaseModel):
    success: bool
    project: str
    session_id: str
    results: dict
    note: Optional[str] = None


# ============================================================================
# BRIDGE CHAT CONTRACTS
# ============================================================================

QueryIntent = Literal[
    "status_query", "next_action", "fact_recall", "session_history",
    "empire_summary", "cost_query", "launch_session", "save_memory", "general"
]


class BridgeChatRequest(BaseModel):
    message: str
    conversation_id: Optional[UUID] = None
    stream: bool = True
    voice_input: bool = False
    audio_base64: Optional[str] = None
    force_model: Optional[str] = None


class ActionDirective(BaseModel):
    action_type: Literal[
        "launch_session", "send_message", "focus_window",
        "send_note", "brain_query", "custom"
    ]
    trigger_type: Literal["immediate", "on_session_end", "on_schedule", "on_condition"] = "immediate"
    trigger_config: dict = Field(default_factory=dict)
    target_project: Optional[str] = None
    target_session: Optional[str] = None
    payload: dict


class BridgeSources(BaseModel):
    handoffs: list[dict] = Field(default_factory=list)
    memories: list[dict] = Field(default_factory=list)
    projects: list[dict] = Field(default_factory=list)
    cards: list[dict] = Field(default_factory=list)


class BridgeTurn(BaseModel):
    id: UUID
    conversation_id: UUID
    turn_number: int
    user_message: str
    assistant_message: str
    model: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: Optional[float] = None
    sources_used: dict = Field(default_factory=dict)
    actions_queued: list[dict] = Field(default_factory=list)
    intent: Optional[QueryIntent] = None
    voice_input: bool = False
    created_at: datetime


class BridgeConversation(BaseModel):
    id: UUID
    title: Optional[str] = None
    started_at: datetime
    last_turn_at: datetime
    total_tokens: int = 0
    total_cost: float = 0.0
    turn_count: int = 0
    project_slug: Optional[str] = None
    saved_to_brain: bool = False


# ============================================================================
# HISTORY LOG CONTRACTS
# ============================================================================

EventCategory = Literal[
    "session", "approval", "bridge", "handoff", "budget",
    "action", "setting", "voice", "chrome", "launch", "auto_approve", "error"
]

EventOutcome = Literal["success", "failure", "pending", "cancelled"]


class HistoryEvent(BaseModel):
    event_type: str
    event_category: EventCategory
    actor: str
    project_slug: Optional[str] = None
    session_id: Optional[str] = None
    action: str
    target: Optional[str] = None
    before_state: Optional[dict] = None
    after_state: Optional[dict] = None
    outcome: Optional[EventOutcome] = None
    details: dict = Field(default_factory=dict)
    cost_usd: Optional[float] = None
    tokens: Optional[int] = None


# ============================================================================
# SETTINGS CONTRACTS
# ============================================================================

SettingsNamespace = Literal[
    "watcher", "summarizer", "budget", "brain", "notifications",
    "voice", "bridge", "data", "appearance", "chrome", "integrations"
]


class SettingRow(BaseModel):
    namespace: SettingsNamespace
    key: str
    value: Any
    description: Optional[str] = None
    updated_at: datetime
    updated_by: Optional[str] = None


class SettingUpdate(BaseModel):
    namespace: SettingsNamespace
    key: str
    value: Any


# ============================================================================
# AUTO-APPROVE CONTRACTS
# ============================================================================

RuleType = Literal["allow", "deny"]
PatternType = Literal["regex", "glob", "exact"]


class AutoApproveRule(BaseModel):
    id: Optional[UUID] = None
    project_slug: str
    rule_type: RuleType
    pattern: str
    pattern_type: PatternType
    max_per_hour: int = 10
    enabled: bool = True
    fire_count: int = 0
    last_fired: Optional[datetime] = None


# ============================================================================
# ACTION QUEUE CONTRACTS
# ============================================================================

ActionType = Literal[
    "launch_session", "send_message", "focus_window",
    "send_note", "brain_query", "custom"
]
TriggerType = Literal["immediate", "on_session_end", "on_schedule", "on_condition"]
ActionStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class QueuedAction(BaseModel):
    id: Optional[UUID] = None
    action_type: ActionType
    trigger_type: TriggerType
    trigger_config: dict = Field(default_factory=dict)
    target_project: Optional[str] = None
    target_session: Optional[str] = None
    payload: dict
    status: ActionStatus = "queued"
    scheduled_for: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    result: Optional[dict] = None
    error_message: Optional[str] = None


# ============================================================================
# PROJECT CONTRACTS
# ============================================================================

BudgetBehavior = Literal["warn", "soft", "hard"]


class Project(BaseModel):
    slug: str
    display_name: str
    emoji: Optional[str] = None
    color: str = "#00E5FF"
    repo_path: Optional[str] = None
    description: Optional[str] = None
    daily_budget_usd: Optional[float] = None
    weekly_budget_usd: Optional[float] = None
    budget_behavior: BudgetBehavior = "warn"
    auto_approve_enabled: bool = False
    notification_overrides: dict = Field(default_factory=dict)
    last_synced_from_brain: Optional[datetime] = None


# ============================================================================
# NOTES CONTRACTS
# ============================================================================

class SessionNote(BaseModel):
    id: Optional[UUID] = None
    project_slug: str
    session_id: Optional[str] = None
    note_text: str
    tags: list[str] = Field(default_factory=list)
    brain_sync: Literal["pending", "sent", "failed"] = "pending"


# ============================================================================
# BRAIN API CONTRACTS (what CodeDeck calls on Brain)
# ============================================================================

ContextDepth = Literal["minimal", "standard", "deep"]


class BrainContextResponse(BaseModel):
    """Response from GET /codedeck/context/{slug}?depth=X"""
    project: str
    depth: str
    injection_prompt: str
    recent_handoffs: list[dict] = Field(default_factory=list)
    memories: list[dict] = Field(default_factory=list)
    current_state: dict = Field(default_factory=dict)


class BrainFlushResponse(BaseModel):
    success: bool
    flushed_count: int
    remaining_queue: int


# ============================================================================
# WATCHER LOCAL API CONTRACTS (localhost:7171)
# ============================================================================

class WatcherStatus(BaseModel):
    healthy: bool
    machine_id: str
    poll_interval: int
    active_sessions: int
    last_poll: Optional[datetime] = None
    version: str


class TerminalFocusRequest(BaseModel):
    session_id: str


class TerminalSendKeysRequest(BaseModel):
    session_id: str
    keys: str
    submit: bool = True
