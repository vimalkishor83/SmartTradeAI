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
