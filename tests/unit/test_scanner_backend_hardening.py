"""Regression checks for Delta scanner API safety and cache concurrency."""

from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest
from werkzeug.datastructures import MultiDict


def test_screener_universe_cold_requests_share_one_build(app, monkeypatch):
    from app.api.v1 import scanner

    values = {}
    build_count = 0
    count_lock = threading.Lock()

    monkeypatch.setattr(scanner.cache, "get", lambda key: values.get(key))
    monkeypatch.setattr(scanner.cache, "set", lambda key, value, timeout=None: values.__setitem__(key, value))

    def build(asset_type):
        nonlocal build_count
        with count_lock:
            build_count += 1
        time.sleep(0.05)
        return [{"symbol": asset_type}]

    monkeypatch.setattr(scanner.market_screener, "_compute_universe", build)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: scanner.get_delta_screener_universe("perpetual_futures"), range(2)))

    assert build_count == 1
    assert results == [[{"symbol": "perpetual_futures"}]] * 2


def test_indicator_universe_cold_requests_share_one_build(app, monkeypatch):
    from app.api.v1 import scanner

    values = {}
    build_count = 0
    count_lock = threading.Lock()

    monkeypatch.setattr(scanner.cache, "get", lambda key: values.get(key))
    monkeypatch.setattr(scanner.cache, "set", lambda key, value, timeout=None: values.__setitem__(key, value))

    def build(asset_type, timeframe):
        nonlocal build_count
        with count_lock:
            build_count += 1
        time.sleep(0.05)
        return [{"symbol": f"{asset_type}:{timeframe}"}]

    monkeypatch.setattr(scanner.indicator_scanner, "compute_universe", build)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: scanner.get_delta_indicator_universe("spot", "15m"),
            range(2),
        ))

    assert build_count == 1
    assert results == [[{"symbol": "spot:15m"}]] * 2


def test_screener_query_contract_rejects_malformed_conditions_and_combinator():
    from app.api.v1.scanner import _ScreenerRequestError, _parse_screener_request

    with pytest.raises(_ScreenerRequestError):
        _parse_screener_request(MultiDict([("conditions", '[{"field":"price"}, 1]')]))
    with pytest.raises(_ScreenerRequestError):
        _parse_screener_request(MultiDict([("combinator", "XOR")]))


def test_scan_body_contract_rejects_invalid_filters(app):
    from app.api.v1 import scanner

    with app.test_request_context("/api/v1/scanner/run", method="POST", json={"filters": "strong_buy"}):
        response, status = scanner.run_scan.__wrapped__()

    assert status == 422
    assert response.get_json()["error"] == "filters must be a list of strings"


def test_scan_market_normalizes_empty_all_markets_value():
    from app.api.v1.scanner import _normalize_scan_market

    assert _normalize_scan_market("") is None
    assert _normalize_scan_market(None) is None
    assert _normalize_scan_market("crypto") == "crypto"


def test_buy_and_strong_buy_are_distinct_conditions():
    """"buy" must be a genuinely broader condition than "strong_buy", not
    an alias resolving to the same result -- a prior bug mapped the
    frontend's "Buy" chip straight onto strong_buy's check, so selecting
    Buy alone showed identical results to Strong Buy."""
    import pandas as pd
    from app.api.v1.scanner import _apply_filters

    df = pd.DataFrame({
        "close": [100.0] * 30, "open": [100.0] * 30,
        "high": [101.0] * 30, "low": [99.0] * 30,
        "volume": [1000.0] * 30,
    })
    # Bullish trend/momentum, but RSI outside strong_buy's 50-70 band --
    # should match the broader "buy" condition without matching strong_buy.
    ind = {"rsi": 75, "ema20": 105, "ema50": 100, "macd_hist": 1.5}
    matched = _apply_filters(df, ind, ["strong_buy", "buy"])
    assert "buy" in matched
    assert "strong_buy" not in matched


def test_sell_and_strong_sell_are_distinct_conditions():
    import pandas as pd
    from app.api.v1.scanner import _apply_filters

    df = pd.DataFrame({
        "close": [100.0] * 30, "open": [100.0] * 30,
        "high": [101.0] * 30, "low": [99.0] * 30,
        "volume": [1000.0] * 30,
    })
    ind = {"rsi": 20, "ema20": 95, "ema50": 100, "macd_hist": -1.5}
    matched = _apply_filters(df, ind, ["strong_sell", "sell"])
    assert "sell" in matched
    assert "strong_sell" not in matched


def test_scan_filters_whitelist_includes_buy_and_sell():
    from app.api.v1.scanner import SCAN_FILTERS

    assert "buy" in SCAN_FILTERS
    assert "sell" in SCAN_FILTERS


def test_scan_endpoint_accepts_empty_all_markets_value(app, monkeypatch):
    from app.api.v1 import scanner

    class EmptyQuery:
        def filter_by(self, **kwargs):
            return self

        def all(self):
            return []

    with app.app_context():
        monkeypatch.setattr(scanner.Asset, "query", EmptyQuery())

        with app.test_request_context(
            "/api/v1/scanner/run",
            method="POST",
            json={"filters": ["strong_buy"], "market": "", "timeframe": "1h"},
        ):
            response, status = scanner.run_scan.__wrapped__()

    assert status == 200
    assert response.get_json() == {"results": [], "count": 0, "scanned": 0}
