"""Parse and strip `[[ACTION: ...]]` tags from assistant responses.

Supported forms:
    [[ACTION: launch_session project="kjwidgetz" prompt="Do X"]]
    [[ACTION: save_memory content="..." tags=["kjwidgetz","pricing"]]]
    [[ACTION: send_note project="kjwidgetz" text="..."]]
    [[ACTION: focus_window session_id="abc123"]]

If the arg parser cannot make sense of the body, the directive is dropped
and a warning is logged — callers should not execute partial actions."""
from __future__ import annotations

import json
import logging
import re

from shared.contracts import ActionDirective

logger = logging.getLogger(__name__)

# `]]` is the terminator, but JSON arrays inside args also end in `]`. We
# use a negative lookahead so the match only ends on `]]` that isn't itself
# followed by another `]` (i.e. not part of an array close).
ACTION_PATTERN = re.compile(r"\[\[ACTION:\s*(\w+)\s+(.+?)\]\](?!\])", re.DOTALL)

# Match key=value pairs where value is one of:
#   "double quoted"      — handles embedded spaces/escapes
#   'single quoted'      — mirror of above
#   [json array]         — balanced brackets, non-greedy
#   bare_token           — no whitespace, no brackets
ARG_PATTERN = re.compile(
    r'(\w+)\s*=\s*'
    r'(?:'
    r'"((?:[^"\\]|\\.)*)"'       # group 2: double-quoted body
    r"|'((?:[^'\\]|\\.)*)'"      # group 3: single-quoted body
    r'|(\[[^\]]*\])'             # group 4: JSON array (unnested)
    r'|([^\s]+)'                 # group 5: bare token
    r')'
)

# Aliases that map human-friendly directive names (what the prompt teaches
# the model to emit) onto the contract's `ActionType` literal. Keeping the
# translation here means the prompt stays readable and the queue row still
# carries a valid action_type the executor can dispatch.
ACTION_ALIASES: dict[str, tuple[str, dict]] = {
    "save_memory": ("brain_query", {"operation": "save"}),
    "recall_memory": ("brain_query", {"operation": "search"}),
}


def parse_directives(text: str) -> list[ActionDirective]:
    directives: list[ActionDirective] = []
    for match in ACTION_PATTERN.finditer(text or ""):
        raw_type, args_str = match.groups()
        try:
            args = _parse_args(args_str)
        except ValueError as exc:
            logger.warning("dropped malformed directive %s: %s", raw_type, exc)
            continue

        action_type = raw_type
        extra_payload: dict = {}
        if raw_type in ACTION_ALIASES:
            action_type, extra_payload = ACTION_ALIASES[raw_type]

        payload = {**extra_payload, **args}
        # Strip project/session_id into top-level fields.
        target_project = payload.pop("project", None)
        target_session = payload.pop("session_id", None)

        try:
            directive = ActionDirective(
                action_type=action_type,  # type: ignore[arg-type]
                target_project=target_project,
                target_session=target_session,
                payload=payload,
            )
        except Exception as exc:
            logger.warning("invalid action %s: %s", raw_type, exc)
            continue

        directives.append(directive)
    return directives


def _parse_args(args_str: str) -> dict:
    """Parse `key=value key="quoted value" list=[...]` into a dict.

    Uses `ARG_PATTERN` to recover each key=value pair. Validates the run
    is consumed fully — a leftover tail indicates malformed input and the
    whole directive is rejected by raising ValueError."""
    args: dict = {}
    pos = 0
    args_str = args_str.strip()
    while pos < len(args_str):
        # Skip leading whitespace between pairs.
        while pos < len(args_str) and args_str[pos].isspace():
            pos += 1
        if pos >= len(args_str):
            break
        m = ARG_PATTERN.match(args_str, pos)
        if not m:
            raise ValueError(f"unparseable at position {pos}: {args_str[pos:pos+40]!r}")
        key = m.group(1)
        double_q, single_q, array_lit, bare = m.group(2), m.group(3), m.group(4), m.group(5)
        if double_q is not None:
            args[key] = double_q.encode().decode("unicode_escape")
        elif single_q is not None:
            args[key] = single_q.encode().decode("unicode_escape")
        elif array_lit is not None:
            try:
                args[key] = json.loads(array_lit)
            except json.JSONDecodeError:
                args[key] = array_lit
        else:
            # Bare token. Reject if it starts with a quote or `[` — those
            # indicate the quoted/array pattern failed to close, i.e.
            # malformed input.
            if bare and bare[0] in ('"', "'", "["):
                raise ValueError(f"unterminated value for {key}={bare!r}")
            try:
                args[key] = json.loads(bare)
            except (json.JSONDecodeError, TypeError):
                args[key] = bare
        pos = m.end()
    return args


def strip_directives(text: str) -> str:
    """Return `text` with all `[[ACTION:...]]` spans removed and trimmed."""
    if not text:
        return ""
    cleaned = ACTION_PATTERN.sub("", text)
    # Collapse the blank lines the removal tends to leave behind.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
