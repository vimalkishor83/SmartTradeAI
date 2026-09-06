"""Contract checks for the risk calculator and portfolio risk view."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "risk.html"


def test_risk_controls_use_bound_events_instead_of_inline_handlers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert "data-direction=\"BUY\"" in source
    assert "data-direction=\"SELL\"" in source
    assert "data-load-signal" in source
    assert "quickSignalsList')?.addEventListener('click'" in source


def test_risk_rendering_bounds_numbers_and_escapes_portfolio_warnings():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "function riskNumber(value, fallback = 0)" in source
    assert "function riskText(value)" in source
    assert "function riskNumberAttr(value)" in source
    assert "const signals = Array.isArray(data?.signals)" in source
    assert "riskText(s.asset || 'Unknown asset')" in source
    assert "riskText(prettyMarket(w))" in source
    assert "riskText(p.symbol_a || 'Unknown')" in source


def test_risk_calculator_enforces_direction_and_exposes_state():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'aria-pressed="true"' in source
    assert 'id="riskValidation"' in source
    assert "const validDirection = _direction === 'BUY'" in source
    assert "Stop Loss must be below Entry" in source
    assert "Stop Loss must be above Entry" in source
    assert "if (value === null || value === undefined || value === '')" in source
