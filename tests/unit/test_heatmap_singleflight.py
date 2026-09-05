"""Regression coverage for the heatmap cold-cache single-flight."""

from concurrent.futures import ThreadPoolExecutor
import threading


def test_cold_heatmap_requests_share_one_build(app, monkeypatch):
    from app.api.v1 import market_data
    from app.extensions import cache

    calls = []
    builder_started = threading.Event()
    release_builder = threading.Event()

    def fake_build():
        calls.append(True)
        builder_started.set()
        assert release_builder.wait(timeout=5)
        return [{"asset_id": 7, "symbol": "TESTUSDT"}]

    cache.delete("market_heatmap")
    monkeypatch.setattr(market_data, "build_heatmap", fake_build)

    def request_heatmap():
        with app.test_request_context("/api/v1/market-data/heatmap"):
            # Bypass only authentication; this test targets the route's
            # shared-cache coordination, not JWT validation.
            return market_data.get_heatmap.__wrapped__()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request_heatmap)
            assert builder_started.wait(timeout=5)
            second = pool.submit(request_heatmap)
            release_builder.set()
            responses = [first.result(timeout=5), second.result(timeout=5)]
    finally:
        cache.delete("market_heatmap")

    assert len(calls) == 1
    assert [response[1] for response in responses] == [200, 200]
    assert all(response[0].json == {"heatmap": [{"asset_id": 7, "symbol": "TESTUSDT"}]} for response in responses)
