"""Contract checks for the live signals and open P&L workflow."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "signals.html"


def test_signal_controls_are_bound_without_inline_handlers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onmouseover=" not in source
    assert "onmouseout=" not in source
    assert "data-signal-tab=\"live\"" in source
    assert "data-action=\"toggle-pnl\"" in source
    assert "data-page-loader=\"${fn}\"" in source
    assert "pnlHeader?.addEventListener('keydown'" in source


def test_signal_payload_rendering_uses_safe_urls_and_finite_values():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function signalNumber(value, fallback = 0)" in source
    assert "function signalText(value)" in source
    assert "STSafe.assetHref(s.asset_id)" in source
    assert "STSafe.assetHref(row.asset_id)" in source
    assert "const signals = Array.isArray(data.signals)" in source
    assert "const history = Array.isArray(data.history)" in source
    assert "let _pnlInFlight = false;" in source
    assert "if (!tbody || !btn || _pnlInFlight) return;" in source
