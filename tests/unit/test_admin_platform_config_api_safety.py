"""Contract checks for safe admin navigation visibility updates."""

from pathlib import Path


ADMIN_API = Path(__file__).parents[2] / "app" / "api" / "v1" / "admin.py"


def test_admin_dashboard_cannot_be_hidden_by_platform_config_api():
    source = ADMIN_API.read_text(encoding="utf-8")

    assert 'item != "/admin"' in source
    assert "disabled_nav_items must contain route strings" in source
