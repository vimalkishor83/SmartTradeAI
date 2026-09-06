"""Contract checks for the strategy backtesting workflow."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "backtesting.html"


def test_backtesting_controls_use_bound_events_and_keyboard_accessible_history():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "onchange=" not in source
    assert "data-backtest-id" in source
    assert "history.addEventListener('keydown'" in source
    assert "document.getElementById('btStrategy')?.addEventListener('change', onStrategyChange)" in source
    assert 'id="backtestingStatus" class="visually-hidden" role="status" aria-live="polite"' in source
    assert '<button type="button" class="btn btn-primary w-100" id="runBt">' in source


def test_backtesting_escapes_api_text_and_bounds_numeric_rendering():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function btNumber(value, fallback = 0)" in source
    assert "function btText(value)" in source
    assert "btText(bt.asset || 'Unknown asset')" in source
    assert "btText(bt.strategy || 'Unknown strategy')" in source
    assert "btText(a.name || '')" in source
    assert "Array.isArray(data?.backtests)" in source
    assert "data.sample_trades.filter(trade => trade && typeof trade === 'object')" in source
    assert "btn.removeAttribute('aria-busy');" in source
    assert "Backtest failed before a result was returned." in source
