"""
Watcher runtime configuration.

Defaults come from env vars; runtime overrides come from `kjcodedeck.settings`.
We do NOT hot-reload — components call reload_settings() explicitly (see
Bridge-B spec §3 and CLAUDE.md rule #3).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

log = logging.getLogger(__name__)

# Load .env from repo root (two levels up from this file: watcher/config.py -> repo/)
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")


@dataclass
class WatcherConfig:
    # ---- Identity / env -----------------------------------------------------
    machine_id: str = os.environ.get("MACHINE_ID", "jim-windows-main")
    admin_key: str = os.environ.get("BRIDGEDECK_ADMIN_KEY", "bridgedeck-kj-2026-kingjames")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    brain_api_url: str = os.environ.get("BRAIN_API_URL", "https://jim-brain-production.up.railway.app")
    brain_key: str = os.environ.get("BRAIN_KEY", "jim-brain-kje-2026-kingjames")
    supabase_url: str = os.environ.get("SUPABASE_URL", "")
    supabase_service_key: str = os.environ.get("SUPABASE_SERVICE_KEY", "")

    # ---- Paths --------------------------------------------------------------
    claude_windows_path: str = os.environ.get(
        "CLAUDE_CODE_WINDOWS_PATH",
        str(Path(os.environ.get("USERPROFILE", r"C:\Users\Jim")) / ".claude"),
    )
    claude_wsl_path: str = os.environ.get(
        "CLAUDE_CODE_WSL_PATH", r"\\wsl$\Ubuntu\home\jim\.claude"
    )

    # ---- Runtime tunables (default; overridden from Supabase settings) ------
    poll_interval_seconds: int = 3
    local_api_port: int = 7171
    tmux_prefix: str = "bridgedeck-"
    preferred_terminal: str = "WindowsTerminal"
    idle_minutes: int = 10

    # Summarizer
    summarizer_default_model: str = "claude-haiku-4-5-20251001"
    summarizer_escalation_model: str = "claude-sonnet-4-5"
    summarizer_escalation_threshold: int = 50_000
    summarizer_confidence_threshold: float = 0.85
    summarizer_prompt_version: str = "v1.0"

    # Raw settings blob so other modules can read exotic keys by namespace+key
    raw: dict[str, Any] = field(default_factory=dict)


_cfg: Optional[WatcherConfig] = None


def get_config() -> WatcherConfig:
    global _cfg
    if _cfg is None:
        _cfg = WatcherConfig()
    return _cfg


def reload_settings() -> WatcherConfig:
    """
    Pull the `settings` table from Supabase and apply known keys.
    Unknown namespace/keys are kept in `.raw` so callers can query them.

    Never raises: if Supabase is unreachable, we log and keep env defaults.
    """
    global _cfg
    cfg = get_config()
    try:
        from watcher.supabase_client import get_supabase

        client = get_supabase()
        if client is None:
            log.warning("Supabase unavailable; using env defaults for settings")
            return cfg

        rows = client.schema("kjcodedeck").table("settings").select("*").execute().data or []
    except Exception as e:  # noqa: BLE001 — settings load is best-effort
        log.warning("Failed to load settings from Supabase: %s", e)
        return cfg

    raw: dict[str, Any] = {}
    for row in rows:
        ns = row.get("namespace")
        key = row.get("key")
        value = row.get("value")
        if ns is None or key is None:
            continue
        raw.setdefault(ns, {})[key] = value

    # Apply known keys (flat dotted-name mapping)
    w = raw.get("watcher", {})
    if "poll_interval_seconds" in w:
        cfg.poll_interval_seconds = int(w["poll_interval_seconds"])
    if "local_api_port" in w:
        cfg.local_api_port = int(w["local_api_port"])
    if "tmux_prefix" in w:
        cfg.tmux_prefix = str(w["tmux_prefix"])
    if "preferred_terminal" in w:
        cfg.preferred_terminal = str(w["preferred_terminal"])
    if "claude_code_windows_path" in w:
        cfg.claude_windows_path = str(w["claude_code_windows_path"])
    if "claude_code_wsl_path" in w:
        cfg.claude_wsl_path = str(w["claude_code_wsl_path"])

    s = raw.get("summarizer", {})
    if "model_default" in s:
        cfg.summarizer_default_model = str(s["model_default"])
    if "model_escalation" in s:
        cfg.summarizer_escalation_model = str(s["model_escalation"])
    if "escalation_token_threshold" in s:
        cfg.summarizer_escalation_threshold = int(s["escalation_token_threshold"])
    if "confidence_threshold" in s:
        cfg.summarizer_confidence_threshold = float(s["confidence_threshold"])
    if "prompt_version" in s:
        cfg.summarizer_prompt_version = str(s["prompt_version"])

    b = raw.get("brain", {})
    if "api_url" in b:
        cfg.brain_api_url = str(b["api_url"])

    cfg.raw = raw
    log.info("Settings reloaded from Supabase (namespaces=%s)", list(raw.keys()))
    return cfg
