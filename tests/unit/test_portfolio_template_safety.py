"""Contract checks for portfolio rendering and position actions."""

from pathlib import Path


TEMPLATE = Path(__file__).parents[2] / "frontend" / "templates" / "dashboard" / "portfolio.html"


def test_portfolio_uses_event_bound_position_actions():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "onclick=" not in source
    assert 'data-remove-position="${id}"' in source
    assert "data-id=\"${id}\"" in source
    assert "document.getElementById('holdingsBody').addEventListener('click'" in source
    assert "document.getElementById('exportPortfolioBtn').addEventListener('click'" in source


def test_portfolio_escapes_provider_values_and_bounds_numbers():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "${h.asset}" not in source
    assert "${_portfolioHtml(h.asset || '—')}" in source
    assert "function _portfolioNumber(value, fallback = null)" in source
    assert "function _portfolioId(value)" in source
    assert "Number.isFinite(number)" in source
    assert "Array.isArray(data.holdings)" in source


def test_portfolio_serializes_mutating_actions_and_reports_failures():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "let _portfolioLoadPromise = null;" in source
    assert "let _addPositionInFlight = false;" in source
    assert "let _stopLossInFlight = false;" in source
    assert "const _removePositionInFlight = new Set();" in source
    assert "if (_addPositionInFlight) return;" in source
    assert "if (ok)" in source
    assert "Failed to remove position" in source


def test_portfolio_notes_match_persisted_column_limit():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="posNotes"' in source
    assert 'maxlength="255"' in source
    assert ".value.slice(0, 255)" in source


def test_portfolio_clears_stale_rows_after_empty_refresh():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert "if (!holdings.length) {" in source
    assert "No positions yet" in source
    assert "MAX_PORTFOLIO_QUANTITY = 1000000000" in source
    assert "MAX_PORTFOLIO_PRICE = 1000000000000" in source
    assert "^[A-Z0-9][A-Z0-9._-]{0,29}$" in source


def test_portfolio_exposes_freshness_and_accessible_loading_state():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="portfolioContext"' in source
    assert 'id="portfolioStatus"' in source
    assert 'caption class="visually-hidden"' in source
    assert 'aria-labelledby="addPositionTitle"' in source
    assert "if (body) body.setAttribute('aria-busy', 'false')" in source
    assert "let _portfolioBooted = false;" in source
