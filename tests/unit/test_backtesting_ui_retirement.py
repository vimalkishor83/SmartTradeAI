"""The removed backtesting UI must not be reintroduced by navigation."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
BASE = ROOT / "frontend" / "templates" / "partials" / "base.html"
LEGACY_TEMPLATE = ROOT / "frontend" / "templates" / "dashboard" / "backtesting.html"


def test_removed_backtesting_ui_has_no_legacy_template_or_sidebar_link():
    source = BASE.read_text(encoding="utf-8")

    assert not LEGACY_TEMPLATE.exists()
    assert 'href="/backtesting"' not in source
    assert 'href="/backtest-sweep"' not in source
