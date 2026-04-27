"""Directive parser tests."""
from bridge_core.directives import parse_directives, strip_directives


def test_parse_launch_session():
    text = 'Sure. [[ACTION: launch_session project="kjwidgetz" prompt="Do the thing"]]'
    directives = parse_directives(text)
    assert len(directives) == 1
    d = directives[0]
    assert d.action_type == "launch_session"
    assert d.target_project == "kjwidgetz"
    assert d.payload == {"prompt": "Do the thing"}


def test_parse_save_memory_with_list():
    text = (
        '[[ACTION: save_memory content="F2 Ultra code is xToolBrandon" '
        'tags=["kjwidgetz","pricing"]]]'
    )
    directives = parse_directives(text)
    assert len(directives) == 1
    d = directives[0]
    # save_memory aliases to brain_query at the contract layer
    assert d.action_type == "brain_query"
    assert d.payload["operation"] == "save"
    assert d.payload["content"].startswith("F2 Ultra")
    assert d.payload["tags"] == ["kjwidgetz", "pricing"]


def test_parse_focus_window_by_session():
    text = 'Focusing. [[ACTION: focus_window session_id="sess-123"]]'
    directives = parse_directives(text)
    assert len(directives) == 1
    assert directives[0].action_type == "focus_window"
    assert directives[0].target_session == "sess-123"
    assert directives[0].payload == {}


def test_strip_directives_leaves_clean_text():
    text = (
        "Kicking off the session now.\n\n"
        '[[ACTION: launch_session project="iasy" prompt="Stripe prompt 3"]]\n\n'
        "I'll ping you when it's done."
    )
    cleaned = strip_directives(text)
    assert "[[ACTION:" not in cleaned
    assert "Kicking off the session now." in cleaned
    assert "I'll ping you when it's done." in cleaned


def test_malformed_directive_dropped():
    text = '[[ACTION: launch_session project="kjwidgetz prompt=dangling]]'
    directives = parse_directives(text)
    assert directives == []


def test_unknown_action_type_dropped():
    text = '[[ACTION: detonate target="prod"]]'
    directives = parse_directives(text)
    assert directives == []


def test_no_directives_returns_empty():
    assert parse_directives("Plain response with no tags.") == []
    assert parse_directives("") == []


def test_multiple_directives():
    text = (
        '[[ACTION: save_memory content="x" tags=["a"]]] then '
        '[[ACTION: send_note project="kjle" text="hi"]]'
    )
    directives = parse_directives(text)
    assert len(directives) == 2
    assert directives[0].action_type == "brain_query"
    assert directives[1].action_type == "send_note"
    assert directives[1].target_project == "kjle"
