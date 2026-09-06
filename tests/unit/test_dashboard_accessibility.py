from pathlib import Path


ROOT = Path(__file__).parents[2]
BASE_TEMPLATE = ROOT / "frontend" / "templates" / "partials" / "base.html"


def test_dashboard_shell_has_keyboard_navigation_landmarks():
    template = BASE_TEMPLATE.read_text(encoding="utf-8")
    assert '<a class="skip-link" href="#pageContent">' in template
    assert '<main class="page-content" id="pageContent">' in template
    assert '<aside class="sidebar" id="sidebar" aria-labelledby="sidebarLabel">' in template
    assert template.count('class="nav-group-header"') == 8
    assert template.count('type="button" class="nav-group-header"') == 8
    assert 'aria-controls="navGroupBodyOverview"' in template
    assert 'role="status" aria-live="polite"' in template


def test_dashboard_navigation_updates_expanded_state():
    template = BASE_TEMPLATE.read_text(encoding="utf-8")
    assert "header.setAttribute('aria-expanded', String(isOpen))" in template
    assert "String(g.classList.contains('open'))" in template
