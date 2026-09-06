"""Regression coverage for single-flight market-data cache misses."""

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from types import SimpleNamespace

import pandas as pd


def _ohlcv_frame(rows=2):
    index = pd.date_range("2026-01-01", periods=rows, freq="h")
    return pd.DataFrame({
        "open": [100.0 + i for i in range(rows)],
        "high": [101.0 + i for i in range(rows)],
        "low": [99.0 + i for i in range(rows)],
        "close": [100.5 + i for i in range(rows)],
        "volume": [10.0 + i for i in range(rows)],
    }, index=index)


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


def test_yahoo_ohlcv_collapses_concurrent_same_key_misses(monkeypatch):
    from app.services.data import fetcher as fetcher_module

    calls = 0
    calls_lock = threading.Lock()

    def download(*_args, **_kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return _ohlcv_frame()

    monkeypatch.setattr(fetcher_module, "_YF_AVAILABLE", True)
    monkeypatch.setattr(fetcher_module, "yf", SimpleNamespace(download=download))
    monkeypatch.setattr(
        fetcher_module,
        "_breaker_yahoo",
        SimpleNamespace(allow=lambda: True, success=lambda: None, failure=lambda: None),
    )
    fetcher_module._cache.clear()
    client = fetcher_module.YahooFetcher()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda _index: client.fetch_ohlcv("NIFTY50", "1h", limit=2),
                range(2),
            ))
    finally:
        fetcher_module._cache.clear()

    assert calls == 1
    assert all(result is not None for result in results)
    assert all(len(result) == 2 for result in results)


def test_yahoo_batch_refetches_short_cached_frame_for_larger_limit(monkeypatch):
    from app.services.data import fetcher as fetcher_module

    calls = 0

    def download(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _ohlcv_frame(rows=3)

    monkeypatch.setattr(fetcher_module, "_YF_AVAILABLE", True)
    monkeypatch.setattr(fetcher_module, "yf", SimpleNamespace(download=download))
    fetcher_module._cache.clear()
    fetcher_module._cache.set("NIFTY50_1h", _ohlcv_frame(rows=2))
    client = fetcher_module.YahooFetcher()

    try:
        result = client.fetch_ohlcv_batch(["NIFTY50"], "1h", limit=3)
    finally:
        fetcher_module._cache.clear()

    assert calls == 1
    assert len(result["NIFTY50"]) == 3


def test_non_crypto_ticker_collapses_concurrent_cache_misses(monkeypatch):
    from app.services.data import fetcher as fetcher_module

    calls = 0
    calls_lock = threading.Lock()

    class _Info:
        last_price = 22000.0

    class _Ticker:
        def __init__(self, _symbol):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.05)

        @property
        def fast_info(self):
            return _Info()

    monkeypatch.setattr(fetcher_module, "_YF_AVAILABLE", True)
    monkeypatch.setattr(fetcher_module, "yf", SimpleNamespace(Ticker=_Ticker))
    fetcher_module._ticker_cache._store.clear()
    client = fetcher_module.MarketDataFetcher()
    asset = SimpleNamespace(symbol="NIFTY50", market="index")

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: client.fetch_ticker(asset), range(2)))
    finally:
        fetcher_module._ticker_cache._store.clear()

    assert calls == 1
    assert all(result["price"] == 22000.0 for result in results)
