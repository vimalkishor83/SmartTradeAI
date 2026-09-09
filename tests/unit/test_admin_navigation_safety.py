"""Contract checks for the compact admin navigation model."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
BASE = ROOT / "frontend" / "templates" / "partials" / "base.html"
ADMIN = ROOT / "frontend" / "templates" / "admin" / "index.html"


def test_dashboard_duplicate_admin_destinations_are_not_persistent_submenus():
    base = BASE.read_text(encoding="utf-8")

    for tooltip in ("Users", "API Configs", "Audit Log", "Daily Compound Calculator"):
        assert f'data-tooltip="{tooltip}"' not in base

    for href in (
        "/admin",
        "/admin/assets",
        "/admin/logs",
        "/admin/platform-config",
        "/admin/telegram-alerts",
        "/admin/security",
        "/admin/sessions",
        "/auto-generate",
    ):
        assert f'href="{href}"' in base


def test_admin_dashboard_keeps_removed_submenus_discoverable():
    admin = ADMIN.read_text(encoding="utf-8")

    for href in (
        "/admin/users",
        "/admin/api-configs",
        "/admin/audit-log",
        "/admin/daily-compound-calculator",
    ):
        assert f'href="{href}"' in admin

    assert "Admin Tools" in admin
    assert "admin-tool-link" in admin
