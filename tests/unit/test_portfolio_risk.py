"""
Portfolio correlation/concentration risk (feature 3 of this session's
build) — pure functions, no I/O.
"""
import numpy as np
import pandas as pd

from app.services.risk.portfolio_risk import (
    calculate_correlation_matrix,
    calculate_concentration,
)


class TestCorrelationMatrix:
    def test_perfectly_correlated_series_flagged(self):
        idx = pd.date_range("2024-01-01", periods=30)
        base = pd.Series(np.linspace(100, 120, 30), index=idx)
        scaled = base * 1.5  # scalar multiple -> perfectly correlated returns
        result = calculate_correlation_matrix({"A": base, "B": scaled})
        assert result["symbols"] == ["A", "B"]
        assert result["matrix"][0][1] == 1.0
        assert len(result["high_correlation_pairs"]) == 1
        assert result["high_correlation_pairs"][0]["correlation"] == 1.0

    def test_independent_series_not_flagged(self):
        idx = pd.date_range("2024-01-01", periods=50)
        rng = np.random.RandomState(42)
        a = pd.Series(100 + rng.randn(50).cumsum(), index=idx)
        b = pd.Series(100 + rng.randn(50).cumsum(), index=idx)
        result = calculate_correlation_matrix({"A": a, "B": b})
        assert len(result["high_correlation_pairs"]) == 0

    def test_single_symbol_returns_empty_matrix(self):
        idx = pd.date_range("2024-01-01", periods=10)
        result = calculate_correlation_matrix({"A": pd.Series(range(10), index=idx)})
        assert result["matrix"] == []
        assert result["high_correlation_pairs"] == []

    def test_no_symbols_returns_empty(self):
        result = calculate_correlation_matrix({})
        assert result["symbols"] == []
        assert result["matrix"] == []

    def test_short_series_excluded_from_correlation(self):
        idx = pd.date_range("2024-01-01", periods=30)
        long_series = pd.Series(range(30), index=idx)
        short_series = pd.Series([1, 2], index=idx[:2])
        result = calculate_correlation_matrix({"A": long_series, "B": short_series})
        # B has < 3 points, should be dropped entirely — only A remains,
        # which alone can't form a pair, so matrix is empty.
        assert "B" not in result["symbols"]


class TestConcentration:
    def test_single_symbol_percentage_correct(self):
        result = calculate_concentration([
            {"symbol": "A", "market": "crypto", "value": 5000},
            {"symbol": "B", "market": "crypto", "value": 5000},
        ])
        assert result["total_value"] == 10000
        assert result["by_symbol"][0]["pct"] == 50.0

    def test_flags_high_single_symbol_concentration(self):
        result = calculate_concentration([
            {"symbol": "A", "market": "crypto", "value": 8000},
            {"symbol": "B", "market": "crypto", "value": 2000},
        ])
        assert any("A is" in w for w in result["warnings"])

    def test_flags_high_market_concentration(self):
        result = calculate_concentration([
            {"symbol": "A", "market": "crypto", "value": 9000},
            {"symbol": "B", "market": "forex", "value": 1000},
        ])
        assert any("crypto" in w for w in result["warnings"])

    def test_well_diversified_portfolio_has_no_warnings(self):
        result = calculate_concentration([
            {"symbol": "A", "market": "crypto", "value": 2000},
            {"symbol": "B", "market": "forex", "value": 2000},
            {"symbol": "C", "market": "indian_stock", "value": 2000},
            {"symbol": "D", "market": "commodity", "value": 2000},
            {"symbol": "E", "market": "index", "value": 2000},
        ])
        assert result["warnings"] == []

    def test_empty_holdings_returns_zero_total(self):
        result = calculate_concentration([])
        assert result["total_value"] == 0
        assert result["warnings"] == []

    def test_by_symbol_sorted_descending_by_pct(self):
        result = calculate_concentration([
            {"symbol": "A", "market": "crypto", "value": 1000},
            {"symbol": "B", "market": "crypto", "value": 5000},
            {"symbol": "C", "market": "crypto", "value": 3000},
        ])
        pcts = [s["pct"] for s in result["by_symbol"]]
        assert pcts == sorted(pcts, reverse=True)
