from pathlib import Path


ROOT = Path(__file__).parents[2]
PAGE = ROOT / "frontend" / "templates" / "admin" / "cleanup.html"


def test_cleanup_page_is_read_only_and_uses_safe_api_client():
    source = PAGE.read_text(encoding="utf-8")

    assert "API.get('/admin/cleanup/status')" in source
    assert "API.delete" not in source
    assert "--apply" not in source
    assert "arbitrary paths" in source
    assert "STSafe.html(root.path" in source


def test_cleanup_page_is_reachable_from_admin_navigation():
    base = (ROOT / "frontend/templates/partials/base.html").read_text(encoding="utf-8")
    admin = (ROOT / "frontend/templates/admin/index.html").read_text(encoding="utf-8")
    platform = (ROOT / "frontend/templates/admin/platform_config.html").read_text(encoding="utf-8")

    assert 'href="/admin/cleanup"' in base
    assert 'href="/admin/cleanup"' in admin
    assert "['/admin/cleanup', 'Cleanup Monitor']" in platform
