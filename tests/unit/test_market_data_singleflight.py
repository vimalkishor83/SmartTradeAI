"""Regression coverage for single-flight market-data cache misses."""

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from types import SimpleNamespace


def test_delta_ohlcv_collapses_concurrent_same_key_misses(monkeypatch):
    from app.services.data import fetcher as fetcher_module

    calls = 0
    calls_lock = threading.Lock()

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": [
                {"time": 1, "open": "100", "high": "101", "low": "99", "close": "100.5", "volume": "10"},
                {"time": 2, "open": "100.5", "high": "102", "low": "100", "close": "101", "volume": "12"},
            ]}

    class _Session:
        def get(self, *_args, **_kwargs):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.05)
            return _Response()

    monkeypatch.setattr(fetcher_module, "_http_session", _Session())
    monkeypatch.setattr(fetcher_module, "_delta_live_symbols", lambda: {"BTCUSD"})
    monkeypatch.setattr(
        fetcher_module,
        "_breaker_delta",
        SimpleNamespace(allow=lambda: True, success=lambda: None, failure=lambda: None),
    )
    fetcher_module._cache.clear()
    client = fetcher_module.DeltaExchangeFetcher()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda _index: client.fetch_ohlcv("BTCUSDT", "1h", limit=2),
                range(2),
            ))
    finally:
        fetcher_module._cache.clear()

    assert calls == 1
    assert all(result is not None for result in results)
    assert all(len(result) == 2 for result in results)
