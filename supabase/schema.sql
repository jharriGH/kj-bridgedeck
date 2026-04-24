-- KJ BridgeDeck Schema v1.0
-- Target: dhzpwobfihrprlcxqjbq
-- Run in Supabase SQL Editor

CREATE SCHEMA IF NOT EXISTS kjcodedeck;

-- 1. live_sessions — ephemeral, updates every 3 sec
CREATE TABLE kjcodedeck.live_sessions (
    session_id       TEXT PRIMARY KEY,
    project_slug     TEXT NOT NULL,
    machine_id       TEXT NOT NULL,
    pid              INTEGER,
    cwd              TEXT,
    terminal_app     TEXT,
    window_title     TEXT,
    tmux_session     TEXT,
    status           TEXT NOT NULL CHECK (status IN ('processing','waiting','needs_input','idle','ended')),
    model            TEXT,
    tokens_in        INTEGER DEFAULT 0,
    tokens_out       INTEGER DEFAULT 0,
    cost_usd         NUMERIC(10,4) DEFAULT 0,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    jsonl_path       TEXT,
    needs_input_msg  TEXT,
    metadata         JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX idx_live_sessions_project ON kjcodedeck.live_sessions(project_slug);
CREATE INDEX idx_live_sessions_status ON kjcodedeck.live_sessions(status) WHERE status != 'ended';
CREATE INDEX idx_live_sessions_machine ON kjcodedeck.live_sessions(machine_id);

-- 2. session_archive — raw JSONL per completed session
CREATE TABLE kjcodedeck.session_archive (
    session_id       TEXT PRIMARY KEY,
    project_slug     TEXT NOT NULL,
    jsonl_raw        TEXT NOT NULL,
    token_total      INTEGER,
    cost_total       NUMERIC(10,4),
    started_at       TIMESTAMPTZ NOT NULL,
    ended_at         TIMESTAMPTZ NOT NULL,
    archived_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_session_archive_project ON kjcodedeck.session_archive(project_slug);
CREATE INDEX idx_session_archive_ended ON kjcodedeck.session_archive(ended_at DESC);

-- 3. session_handoffs — structured Haiku summaries
CREATE TABLE kjcodedeck.session_handoffs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       TEXT NOT NULL REFERENCES kjcodedeck.session_archive(session_id),
    project_slug     TEXT NOT NULL,
    summary          TEXT NOT NULL,
    decisions        JSONB DEFAULT '[]'::jsonb,
    artifacts        JSONB DEFAULT '[]'::jsonb,
    next_action      TEXT,
    token_cost       NUMERIC(10,4),
    confidence       NUMERIC(3,2) CHECK (confidence >= 0 AND confidence <= 1),
    status           TEXT CHECK (status IN ('completed','aborted','partial')),
    summarizer_model TEXT,
    brain_sync       TEXT DEFAULT 'pending' CHECK (brain_sync IN ('pending','sent','failed','rejected')),
    brain_response   JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_handoffs_project ON kjcodedeck.session_handoffs(project_slug, created_at DESC);
CREATE INDEX idx_handoffs_brain_sync ON kjcodedeck.session_handoffs(brain_sync) WHERE brain_sync = 'pending';

-- 4. session_notes — user-typed persistent context
CREATE TABLE kjcodedeck.session_notes (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_slug     TEXT NOT NULL,
    session_id       TEXT,
    note_text        TEXT NOT NULL,
    tags             TEXT[] DEFAULT ARRAY[]::TEXT[],
    brain_sync       TEXT DEFAULT 'pending' CHECK (brain_sync IN ('pending','sent','failed')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_notes_project ON kjcodedeck.session_notes(project_slug);

-- 5. history_log — comprehensive audit trail
CREATE TABLE kjcodedeck.history_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type       TEXT NOT NULL,
    event_category   TEXT NOT NULL CHECK (event_category IN (
                        'session','approval','bridge','handoff','budget',
                        'action','setting','voice','chrome','launch','auto_approve','error')),
    actor            TEXT NOT NULL,
    project_slug     TEXT,
    session_id       TEXT,
    action           TEXT NOT NULL,
    target           TEXT,
    before_state     JSONB,
    after_state      JSONB,
    outcome          TEXT CHECK (outcome IN ('success','failure','pending','cancelled')),
    details          JSONB DEFAULT '{}'::jsonb,
    cost_usd         NUMERIC(10,4),
    tokens           INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_history_created ON kjcodedeck.history_log(created_at DESC);
CREATE INDEX idx_history_project ON kjcodedeck.history_log(project_slug, created_at DESC);
CREATE INDEX idx_history_category ON kjcodedeck.history_log(event_category, created_at DESC);
CREATE INDEX idx_history_session ON kjcodedeck.history_log(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX idx_history_type ON kjcodedeck.history_log(event_type);

-- 6. settings — admin configuration
CREATE TABLE kjcodedeck.settings (
    namespace        TEXT NOT NULL,
    key              TEXT NOT NULL,
    value            JSONB NOT NULL,
    description      TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by       TEXT,
    PRIMARY KEY (namespace, key)
);

-- 7. auto_approve_rules
CREATE TABLE kjcodedeck.auto_approve_rules (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_slug     TEXT NOT NULL,
    rule_type        TEXT NOT NULL CHECK (rule_type IN ('allow','deny')),
    pattern          TEXT NOT NULL,
    pattern_type     TEXT NOT NULL CHECK (pattern_type IN ('regex','glob','exact')),
    max_per_hour     INTEGER DEFAULT 10,
    enabled          BOOLEAN DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_fired       TIMESTAMPTZ,
    fire_count       INTEGER DEFAULT 0
);
CREATE INDEX idx_auto_approve_project ON kjcodedeck.auto_approve_rules(project_slug, enabled);

-- 8. action_queue — Bridge-scheduled actions
CREATE TABLE kjcodedeck.action_queue (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type      TEXT NOT NULL CHECK (action_type IN (
                        'launch_session','send_message','focus_window',
                        'send_note','brain_query','custom')),
    trigger_type     TEXT NOT NULL CHECK (trigger_type IN (
                        'immediate','on_session_end','on_schedule','on_condition')),
    trigger_config   JSONB DEFAULT '{}'::jsonb,
    target_project   TEXT,
    target_session   TEXT,
    payload          JSONB NOT NULL,
    status           TEXT DEFAULT 'queued' CHECK (status IN (
                        'queued','running','completed','failed','cancelled')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scheduled_for    TIMESTAMPTZ,
    executed_at      TIMESTAMPTZ,
    result           JSONB,
    error_message    TEXT
);
CREATE INDEX idx_action_queue_status ON kjcodedeck.action_queue(status, scheduled_for)
    WHERE status IN ('queued','running');

-- 9. projects — cached from Brain
CREATE TABLE kjcodedeck.projects (
    slug             TEXT PRIMARY KEY,
    display_name     TEXT NOT NULL,
    emoji            TEXT,
    color            TEXT DEFAULT '#00E5FF',
    repo_path        TEXT,
    description      TEXT,
    daily_budget_usd NUMERIC(8,2),
    weekly_budget_usd NUMERIC(8,2),
    budget_behavior  TEXT DEFAULT 'warn' CHECK (budget_behavior IN ('warn','soft','hard')),
    auto_approve_enabled BOOLEAN DEFAULT FALSE,
    notification_overrides JSONB DEFAULT '{}'::jsonb,
    last_synced_from_brain TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 10. bridge_conversations — The Bridge chat history
CREATE TABLE kjcodedeck.bridge_conversations (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title            TEXT,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_turn_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    total_tokens     INTEGER DEFAULT 0,
    total_cost       NUMERIC(10,4) DEFAULT 0,
    turn_count       INTEGER DEFAULT 0,
    project_slug     TEXT,
    saved_to_brain   BOOLEAN DEFAULT FALSE
);

-- 11. bridge_turns — individual conversation turns
CREATE TABLE kjcodedeck.bridge_turns (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  UUID NOT NULL REFERENCES kjcodedeck.bridge_conversations(id) ON DELETE CASCADE,
    turn_number      INTEGER NOT NULL,
    user_message     TEXT NOT NULL,
    assistant_message TEXT NOT NULL,
    model            TEXT,
    tokens_in        INTEGER,
    tokens_out       INTEGER,
    cost_usd         NUMERIC(10,4),
    sources_used     JSONB DEFAULT '{}'::jsonb,
    actions_queued   JSONB DEFAULT '[]'::jsonb,
    intent           TEXT,
    voice_input      BOOLEAN DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_bridge_turns_conv ON kjcodedeck.bridge_turns(conversation_id, turn_number);

-- Seed settings (~70 rows — all 13 admin panels represented)
INSERT INTO kjcodedeck.settings (namespace, key, value, description) VALUES
-- Watcher
('watcher', 'poll_interval_seconds', '3', 'How often to poll'),
('watcher', 'claude_code_windows_path', '"C:\\Users\\Jim\\.claude"', 'Windows native path'),
('watcher', 'claude_code_wsl_path', '"\\\\wsl$\\Ubuntu\\home\\jim\\.claude"', 'WSL2 path'),
('watcher', 'tmux_prefix', '"bridgedeck-"', 'Tmux session prefix'),
('watcher', 'preferred_terminal', '"WindowsTerminal"', 'Default terminal'),
('watcher', 'local_api_port', '7171', 'Watcher HTTP API port'),
-- Summarizer
('summarizer', 'model_default', '"claude-haiku-4-5-20251001"', 'Haiku for short sessions'),
('summarizer', 'model_escalation', '"claude-sonnet-4-5"', 'Sonnet for complex sessions'),
('summarizer', 'escalation_token_threshold', '50000', 'Escalate above this'),
('summarizer', 'confidence_threshold', '0.85', 'Below = Brain review queue'),
('summarizer', 'prompt_version', '"v1.0"', 'Prompt template version'),
-- Budget
('budget', 'empire_daily_cap_usd', '5.00', 'Total daily cap'),
('budget', 'empire_weekly_cap_usd', '30.00', 'Total weekly cap'),
('budget', 'default_project_daily_cap_usd', '2.00', 'Per-project default'),
('budget', 'default_behavior', '"warn"', 'warn/soft/hard'),
('budget', 'warn_threshold_pct', '80', 'Warn at this %'),
-- Brain
('brain', 'api_url', '"https://jim-brain-production.up.railway.app"', 'Brain base URL'),
('brain', 'flush_interval_minutes', '30', 'Memory flush cron'),
('brain', 'context_depth_default', '"standard"', 'Session context depth'),
('brain', 'auto_inject_context', 'true', 'Inject on session open'),
-- Notifications
('notifications', 'desktop_enabled', 'true', 'Browser notifications'),
('notifications', 'slack_enabled', 'false', 'Slack webhook'),
('notifications', 'slack_webhook_url', '""', 'Slack URL'),
('notifications', 'email_enabled', 'false', 'Email via Resend'),
('notifications', 'email_to', '"jim@mobilewebmds.com"', 'Recipient'),
('notifications', 'sms_enabled', 'false', 'Twilio SMS'),
('notifications', 'sms_to', '""', 'Phone number'),
('notifications', 'quiet_hours_start', '"22:00"', 'Silence start'),
('notifications', 'quiet_hours_end', '"07:00"', 'Silence end'),
('notifications', 'events_enabled', '["needs_input","session_end","budget_warn","budget_kill"]', 'Active alerts'),
-- Voice
('voice', 'stt_provider', '"whisper_api"', 'whisper_api/web_speech/whisper_local'),
('voice', 'tts_provider', '"piper"', 'piper/elevenlabs/web_speech'),
('voice', 'tts_enabled', 'true', 'Read responses aloud'),
('voice', 'tts_voice', '"en_US-ryan-high"', 'Voice model'),
('voice', 'tts_speed', '1.1', 'Playback speed'),
('voice', 'push_to_talk', 'true', 'Hold to talk'),
('voice', 'piper_binary_path', '""', 'Piper exe path'),
('voice', 'piper_model_path', '""', 'Voice model path'),
-- Bridge
('bridge', 'default_model', '"auto"', 'auto/haiku/sonnet'),
('bridge', 'haiku_model', '"claude-haiku-4-5-20251001"', 'Haiku model ID'),
('bridge', 'sonnet_model', '"claude-sonnet-4-5"', 'Sonnet model ID'),
('bridge', 'temperature', '0.7', 'Generation temp'),
('bridge', 'context_depth', '"standard"', 'Brain injection depth'),
('bridge', 'auto_save_conversations', 'true', 'Save to Brain memory'),
('bridge', 'conversation_retention_days', '90', 'Retention'),
-- Data
('data', 'session_archive_retention_days', '365', 'JSONL retention'),
('data', 'history_log_retention_days', '365', 'Audit retention'),
('data', 'live_session_cleanup_hours', '48', 'Purge ended after'),
-- Appearance
('appearance', 'theme', '"hud_dark"', 'Theme name'),
('appearance', 'accent_cyan', '"#00E5FF"', 'Primary accent'),
('appearance', 'accent_gold', '"#FFD700"', 'Secondary accent'),
('appearance', 'background', '"#010810"', 'Base bg'),
('appearance', 'font_size', '"14"', 'Base px'),
('appearance', 'density', '"comfortable"', 'compact/comfortable/spacious'),
('appearance', 'default_tab', '"monitor"', 'Default open tab'),
-- Chrome
('chrome', 'auto_tag_enabled', 'true', 'Auto-tag tabs'),
('chrome', 'focus_behavior', '"raise_and_activate"', 'Focus style'),
('chrome', 'title_parse_rules', '[]', 'Auto-tag regex rules'),
-- Integrations
('integrations', 'gmail_enabled', 'false', 'Gmail MCP'),
('integrations', 'github_enabled', 'false', 'GitHub MCP'),
('integrations', 'calendar_enabled', 'false', 'Calendar MCP'),
('integrations', 'discord_webhook', '""', 'Discord URL');

-- RLS
ALTER TABLE kjcodedeck.live_sessions         ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.session_archive       ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.session_handoffs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.session_notes         ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.history_log           ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.settings              ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.auto_approve_rules    ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.action_queue          ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.projects              ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.bridge_conversations  ENABLE ROW LEVEL SECURITY;
ALTER TABLE kjcodedeck.bridge_turns          ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON kjcodedeck.live_sessions         FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON kjcodedeck.session_archive       FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON kjcodedeck.session_handoffs      FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON kjcodedeck.session_notes         FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON kjcodedeck.history_log           FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON kjcodedeck.settings              FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON kjcodedeck.auto_approve_rules    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON kjcodedeck.action_queue          FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON kjcodedeck.projects              FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON kjcodedeck.bridge_conversations  FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON kjcodedeck.bridge_turns          FOR ALL USING (auth.role() = 'service_role');
