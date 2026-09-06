"""Verify expensive indicator summary cache misses are single-flight."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading
import time


def _run_view(app, view, path):
    with app.test_request_context(path):
        response, status = view.__wrapped__()
        return status, response.get_json()


def test_ta_summary_cold_requests_share_one_build(app, monkeypatch):
    from app.api.v1 import market_data
    from app.auth import decorators

    cache_values = {}
    build_count = 0
    count_lock = threading.Lock()

    def fake_get(key):
        return cache_values.get(key)

    def fake_set(key, value, timeout=None):
        cache_values[key] = value

    def fake_build():
        nonlocal build_count
        with count_lock:
            build_count += 1
        time.sleep(0.05)
        return {"assets": [{"id": 1, "market": "crypto"}], "timeframes": ["1h"]}

    monkeypatch.setattr(market_data.cache, "get", fake_get)
    monkeypatch.setattr(market_data.cache, "set", fake_set)
    monkeypatch.setattr(market_data, "_build_ta_summary_cache", fake_build)
    monkeypatch.setattr(market_data, "_filter_summary_assets", lambda payload, user_id, market: payload["assets"])
    monkeypatch.setattr(decorators, "get_current_user", lambda: SimpleNamespace(id=7))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _run_view(app, market_data.ta_summary, "/ta-summary"), range(2)))

    assert build_count == 1
    assert all(status == 200 for status, _ in results)


def test_ema_summary_cold_requests_share_one_build(app, monkeypatch):
    from app.api.v1 import market_data
    from app.auth import decorators

    cache_values = {}
    build_count = 0
    count_lock = threading.Lock()

    def fake_get(key):
        return cache_values.get(key)

    def fake_set(key, value, timeout=None):
        cache_values[key] = value

    def fake_build(higher_tf_map):
        nonlocal build_count
        with count_lock:
            build_count += 1
        time.sleep(0.05)
        return {"assets": [{"id": 1, "market": "crypto"}], "timeframes": ["1h"]}

    monkeypatch.setattr(market_data.cache, "get", fake_get)
    monkeypatch.setattr(market_data.cache, "set", fake_set)
    monkeypatch.setattr(market_data, "_build_ema_summary_cache", fake_build)
    monkeypatch.setattr(market_data, "_filter_summary_assets", lambda payload, user_id, market: payload["assets"])
    monkeypatch.setattr(decorators, "get_current_user", lambda: SimpleNamespace(id=7))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _run_view(app, market_data.ema_summary, "/ema-summary"), range(2)))

    assert build_count == 1
    assert all(status == 200 for status, _ in results)


def test_ai_summary_singleflight_decorator_serializes_model_work():
    from app.api.v1 import market_data

    build_count = 0
    active_builds = 0
    max_active_builds = 0
    count_lock = threading.Lock()

    @market_data._singleflight(market_data._AI_SUMMARY_BUILD_LOCK)
    def build():
        nonlocal build_count
        nonlocal active_builds, max_active_builds
        with count_lock:
            build_count += 1
            active_builds += 1
            max_active_builds = max(max_active_builds, active_builds)
        time.sleep(0.05)
        with count_lock:
            active_builds -= 1
        return {"status": "ok"}

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: build(), range(2)))

    assert build_count == 2
    assert max_active_builds == 1
    assert results == [{"status": "ok"}, {"status": "ok"}]
