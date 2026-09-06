"""Contract checks for safe admin Login Sessions rendering and controls."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "admin" / "sessions.html"


def test_session_values_are_escaped_and_username_is_not_embedded_in_actions():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "${s.username}" not in source
    assert "${s.ip_address}" not in source
    assert "${s.device}" not in source
    assert "revokeSession(${s.id}" not in source
    assert "STSafe.html(s.username || '—')" in source
    assert "STSafe.html(s.ip_address || '—')" in source
    assert "data-session-username=" in source


def test_session_controls_are_bound_without_inline_handlers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "oninput=" not in source
    assert "onchange=" not in source
    assert "session-row-checkbox" in source
    assert "checkbox.addEventListener('change'" in source
    assert "refreshSessionsBtn" in source
    assert "style=\"display:none!important\"" not in source
