"""
Auto-approve engine.

On a `needs_input` transition, the main loop hands the prompt text + project
slug to `match_and_fire`. Rules come from `kjcodedeck.auto_approve_rules`.
Deny rules win over allow rules. Rate limit: `max_per_hour` per rule.

When an allow rule fires, we route the "accept" keystroke through the
appropriate controller (tmux for WSL sessions, windows_controller for native).
"""
from __future__ import annotations

import fnmatch
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from watcher import history_logger, supabase_client
from watcher import tmux_controller, windows_controller

log = logging.getLogger(__name__)


def _rate_limit_ok(rule: dict) -> bool:
    max_per_hour = int(rule.get("max_per_hour") or 10)
    fire_count = int(rule.get("fire_count") or 0)
    last_fired = rule.get("last_fired")
    if fire_count < max_per_hour:
        return True
    if not last_fired:
        return True
    try:
        ts = datetime.fromisoformat(str(last_fired).replace("Z", "+00:00"))
    except ValueError:
        return True
    # If we've fired N times in the past hour, deny until that window elapses.
    return datetime.now(timezone.utc) - ts > timedelta(hours=1)


def _pattern_matches(pattern: str, pattern_type: str, text: str) -> bool:
    try:
        if pattern_type == "exact":
            return pattern.strip() == text.strip()
        if pattern_type == "glob":
            return fnmatch.fnmatchcase(text, pattern)
        if pattern_type == "regex":
            return re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) is not None
    except re.error as e:
        log.debug("regex compile error for %r: %s", pattern, e)
        return False
    return False


def evaluate_rules(rules: list[dict], prompt_text: str) -> Optional[dict]:
    """
    Returns the winning rule dict, or None if no action. Deny rules short-circuit.
    Allow rules win only if they match AND are rate-limit-clean.
    """
    deny_hit: Optional[dict] = None
    allow_hit: Optional[dict] = None
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if not _pattern_matches(rule.get("pattern", ""), rule.get("pattern_type", "exact"), prompt_text):
            continue
        if rule.get("rule_type") == "deny":
            deny_hit = rule
            break
        if rule.get("rule_type") == "allow" and allow_hit is None:
            allow_hit = rule
    if deny_hit is not None:
        return deny_hit
    if allow_hit is not None and _rate_limit_ok(allow_hit):
        return allow_hit
    return None


def fire_accept(session: dict) -> bool:
    """Send the 'accept' keystroke to the session. Returns True on success."""
    tmux_name = session.get("tmux_session")
    pid = session.get("pid")
    if tmux_name:
        return tmux_controller.send_keys_to_tmux(tmux_name, "1", submit=True)
    if pid:
        return windows_controller.send_key_by_pid(int(pid), "enter")
    return False


def match_and_fire(session: dict, prompt_text: str) -> Optional[str]:
    """
    Evaluate rules for this session's project and take action.
    Returns one of: "fired", "denied", None (no match).
    """
    project_slug = session.get("project_slug")
    if not project_slug:
        return None
    rules = supabase_client.fetch_auto_approve_rules(project_slug)
    if not rules:
        return None
    winner = evaluate_rules(rules, prompt_text)
    if winner is None:
        return None

    if winner.get("rule_type") == "deny":
        history_logger.quick(
            event_type="auto_approve.denied",
            event_category="auto_approve",
            action="denied",
            project_slug=project_slug,
            session_id=session.get("session_id"),
            target=winner.get("pattern"),
            outcome="cancelled",
            details={"pattern_type": winner.get("pattern_type"), "prompt_preview": prompt_text[:200]},
        )
        return "denied"

    success = fire_accept(session)
    supabase_client.bump_auto_approve_rule(winner["id"])
    history_logger.quick(
        event_type="auto_approve.fired",
        event_category="auto_approve",
        action="fired",
        project_slug=project_slug,
        session_id=session.get("session_id"),
        target=winner.get("pattern"),
        outcome="success" if success else "failure",
        details={
            "pattern_type": winner.get("pattern_type"),
            "prompt_preview": prompt_text[:200],
            "rule_id": winner.get("id"),
        },
    )
    return "fired" if success else "denied"
