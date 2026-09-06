"""Contract checks for safe and serialized admin dashboard rendering."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "admin" / "index.html"


def test_dashboard_uses_safe_dataset_actions_and_shared_api_client():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert "id=\"refreshAdminDashboardBtn\"" in source
    assert "data-user-action=\"toggle\"" in source
    assert "data-user-id=\"${id}\"" in source
    assert "adminUsersBody').addEventListener('click'" in source
    assert "API.delete('/admin/audit-logs')" in source


def test_dashboard_database_values_are_escaped_and_css_values_are_clamped():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "${u.username}" not in source
    assert "${u.email}" not in source
    assert "${l.user}" not in source
    assert "${l.action}" not in source
    assert "${c.name}" not in source
    assert "${c.market||''}" not in source
    assert "STSafe.html(u.username || '—')" in source
    assert "STSafe.html(l.action || '—')" in source
    assert "STSafe.html(c.name || 'Unnamed configuration')" in source
    assert "Math.min(100, Math.max(0, pct))" in source


def test_dashboard_refresh_and_mutations_suppress_duplicate_requests():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "if (_dashboardRefreshInFlight) return;" in source
    assert "if (_auditClearInFlight) return;" in source
    assert "_userToggleInFlight.has(userId)" in source
    assert "await Promise.all([loadUsers(), loadApiConfigs(), loadAuditLogs()])" in source
