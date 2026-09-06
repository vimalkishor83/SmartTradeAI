"""Contract checks for safe admin log/audit rendering and controls."""

from pathlib import Path


ROOT = Path(__file__).parents[2] / "frontend" / "templates" / "admin"


def test_system_logs_escape_database_values_and_render_pagination():
    source = (ROOT / "logs.html").read_text(encoding="utf-8")

    assert "${l.level}" not in source
    assert "${l.module || '—'}" not in source
    assert "${l.message}" not in source
    assert "STSafe.html(l.message || '')" in source
    assert "data.pages || 1" in source
    assert "button.addEventListener('click', () => loadLogs(page))" in source


def test_audit_log_escapes_values_and_uses_event_bindings():
    source = (ROOT / "audit_log.html").read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "oninput=" not in source
    assert "onchange=" not in source
    assert "${l.user}" not in source
    assert "${l.action}" not in source
    assert "${l.resource}" not in source
    assert "STSafe.html(l.user || 'system')" in source
    assert "checkbox.addEventListener('change'" in source
    assert "refreshAuditBtn" in source
    assert 'type="button"' in source
    assert 'id="auditStatus"' in source
    assert "let auditLoading = false;" in source
    assert "Unable to load audit entries. Try Refresh." in source
    assert "button.setAttribute('aria-busy', 'false')" in source
