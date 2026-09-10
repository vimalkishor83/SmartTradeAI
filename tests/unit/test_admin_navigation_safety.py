"""Contract checks for the compact admin navigation model."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
BASE = ROOT / "frontend" / "templates" / "partials" / "base.html"
ADMIN = ROOT / "frontend" / "templates" / "admin" / "index.html"


def test_dashboard_duplicate_admin_destinations_are_not_persistent_submenus():
    base = BASE.read_text(encoding="utf-8")

    for tooltip in ("Users", "API Configs"):
        assert f'data-tooltip="{tooltip}"' not in base

    for href in (
        "/admin/assets",
        "/admin/logs",
        "/admin/platform-config",
        "/admin/telegram-alerts",
        "/admin/telegram-signal-limits",
        "/admin/security",
        "/admin/sessions",
        "/admin/audit-log",
        "/admin/daily-compound-calculator",
        "/auto-generate",
    ):
        assert f'href="{href}"' in base
        assert f"{{% if '{href}' not in disabled_nav_items %}}" in base


def test_admin_dashboard_keeps_removed_submenus_discoverable():
    admin = ADMIN.read_text(encoding="utf-8")

    for href in (
        "/admin/users",
        "/admin/api-configs",
        "/admin/audit-log",
        "/admin/daily-compound-calculator",
        "/admin/telegram-signal-limits",
    ):
        assert f'href="{href}"' in admin

    assert "Admin Tools" in admin
    assert "admin-tool-link" in admin


def test_platform_config_exposes_admin_visibility_controls():
    config = (ROOT / "frontend" / "templates" / "admin" / "platform_config.html").read_text(encoding="utf-8")

    assert "const ADMIN_NAV_ITEMS" in config
    assert 'id="adminPages"' in config
    assert "Admin Panel is always visible" in config
    assert "...ADMIN_NAV_ITEMS.map(([href]) => href)" in config
    assert "['/admin/telegram-signal-limits', 'Signal Limits']" in config
