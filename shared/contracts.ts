/**
 * KJ BridgeDeck — Shared TypeScript contracts.
 * Mirrors shared/contracts.py exactly.
 * Do not modify without coordinating across all components.
 */

// ============================================================================
// SESSION CONTRACTS
// ============================================================================

export type SessionStatus = "processing" | "waiting" | "needs_input" | "idle" | "ended";

export interface LiveSession {
  session_id: string;
  project_slug: string;
  machine_id: string;
  pid: number | null;
  cwd: string | null;
  terminal_app: string | null;
  window_title: string | null;
  tmux_session: string | null;
  status: SessionStatus;
  model: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  started_at: string;
  last_activity: string;
  jsonl_path: string | null;
  needs_input_msg: string | null;
  metadata: Record<string, any>;
}

export interface SessionLaunchRequest {
  project_slug: string;
  initial_prompt?: string;
  working_directory?: string;
}

export interface SessionMessageRequest {
  text: string;
  session_id: string;
}

// ============================================================================
// HANDOFF CONTRACTS
// ============================================================================

export type HandoffStatus = "completed" | "aborted" | "partial";

export interface SessionHandoff {
  project_slug: string;
  summary: string;
  decisions: string[];
  artifacts: string[];
  next_action: string | null;
  token_cost: number;
  session_id: string;
  confidence: number;
  agent: "codedeck_watcher";
  status: HandoffStatus;
}

export interface BrainHandoffResponse {
  success: boolean;
  project: string;
  session_id: string;
  results: Record<string, any>;
  note: string | null;
}

// ============================================================================
// BRIDGE CHAT CONTRACTS
// ============================================================================

export type QueryIntent =
  | "status_query"
  | "next_action"
  | "fact_recall"
  | "session_history"
  | "empire_summary"
  | "cost_query"
  | "launch_session"
  | "save_memory"
  | "general";

export interface BridgeChatRequest {
  message: string;
  conversation_id?: string;
  stream?: boolean;
  voice_input?: boolean;
  audio_base64?: string;
  force_model?: string;
}

export type ActionType =
  | "launch_session"
  | "send_message"
  | "focus_window"
  | "send_note"
  | "brain_query"
  | "custom";

export type TriggerType = "immediate" | "on_session_end" | "on_schedule" | "on_condition";

export interface ActionDirective {
  action_type: ActionType;
  trigger_type: TriggerType;
  trigger_config: Record<string, any>;
  target_project: string | null;
  target_session: string | null;
  payload: Record<string, any>;
}

export interface BridgeSources {
  handoffs: any[];
  memories: any[];
  projects: any[];
  cards: any[];
}

export interface BridgeTurn {
  id: string;
  conversation_id: string;
  turn_number: number;
  user_message: string;
  assistant_message: string;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  sources_used: Record<string, any>;
  actions_queued: any[];
  intent: QueryIntent | null;
  voice_input: boolean;
  created_at: string;
}

export interface BridgeConversation {
  id: string;
  title: string | null;
  started_at: string;
  last_turn_at: string;
  total_tokens: number;
  total_cost: number;
  turn_count: number;
  project_slug: string | null;
  saved_to_brain: boolean;
}

// ============================================================================
// HISTORY LOG CONTRACTS
// ============================================================================

export type EventCategory =
  | "session"
  | "approval"
  | "bridge"
  | "handoff"
  | "budget"
  | "action"
  | "setting"
  | "voice"
  | "chrome"
  | "launch"
  | "auto_approve"
  | "error";

export type EventOutcome = "success" | "failure" | "pending" | "cancelled";

export interface HistoryEvent {
  event_type: string;
  event_category: EventCategory;
  actor: string;
  project_slug?: string;
  session_id?: string;
  action: string;
  target?: string;
  before_state?: Record<string, any>;
  after_state?: Record<string, any>;
  outcome?: EventOutcome;
  details?: Record<string, any>;
  cost_usd?: number;
  tokens?: number;
}

// ============================================================================
// SETTINGS CONTRACTS
// ============================================================================

export type SettingsNamespace =
  | "watcher"
  | "summarizer"
  | "budget"
  | "brain"
  | "notifications"
  | "voice"
  | "bridge"
  | "data"
  | "appearance"
  | "chrome"
  | "integrations";

export interface SettingRow {
  namespace: SettingsNamespace;
  key: string;
  value: any;
  description: string | null;
  updated_at: string;
  updated_by: string | null;
}

export interface SettingUpdate {
  namespace: SettingsNamespace;
  key: string;
  value: any;
}

// ============================================================================
// AUTO-APPROVE CONTRACTS
// ============================================================================

export type RuleType = "allow" | "deny";
export type PatternType = "regex" | "glob" | "exact";

export interface AutoApproveRule {
  id?: string;
  project_slug: string;
  rule_type: RuleType;
  pattern: string;
  pattern_type: PatternType;
  max_per_hour: number;
  enabled: boolean;
  fire_count: number;
  last_fired: string | null;
}

// ============================================================================
// ACTION QUEUE CONTRACTS
// ============================================================================

export type ActionStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface QueuedAction {
  id?: string;
  action_type: ActionType;
  trigger_type: TriggerType;
  trigger_config: Record<string, any>;
  target_project: string | null;
  target_session: string | null;
  payload: Record<string, any>;
  status: ActionStatus;
  scheduled_for: string | null;
  executed_at: string | null;
  result: Record<string, any> | null;
  error_message: string | null;
}

// ============================================================================
// PROJECT CONTRACTS
// ============================================================================

export type BudgetBehavior = "warn" | "soft" | "hard";

export interface Project {
  slug: string;
  display_name: string;
  emoji: string | null;
  color: string;
  repo_path: string | null;
  description: string | null;
  daily_budget_usd: number | null;
  weekly_budget_usd: number | null;
  budget_behavior: BudgetBehavior;
  auto_approve_enabled: boolean;
  notification_overrides: Record<string, any>;
  last_synced_from_brain: string | null;
}

// ============================================================================
// NOTES
// ============================================================================

export interface SessionNote {
  id?: string;
  project_slug: string;
  session_id: string | null;
  note_text: string;
  tags: string[];
  brain_sync: "pending" | "sent" | "failed";
}

// ============================================================================
// BRAIN API CONTRACTS
// ============================================================================

export type ContextDepth = "minimal" | "standard" | "deep";

export interface BrainContextResponse {
  project: string;
  depth: string;
  injection_prompt: string;
  recent_handoffs: any[];
  memories: any[];
  current_state: Record<string, any>;
}

// ============================================================================
// WATCHER LOCAL API
// ============================================================================

export interface WatcherStatus {
  healthy: boolean;
  machine_id: string;
  poll_interval: number;
  active_sessions: number;
  last_poll: string | null;
  version: string;
}

export interface TerminalFocusRequest {
  session_id: string;
}

export interface TerminalSendKeysRequest {
  session_id: string;
  keys: string;
  submit: boolean;
}
