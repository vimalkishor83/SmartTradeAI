"""Regression coverage for the economic-calendar cold-cache single-flight."""

from concurrent.futures import ThreadPoolExecutor
import threading


def test_cold_calendar_requests_share_one_provider_refresh(app, monkeypatch):
    from app.api.v1 import news
    from app.extensions import cache

    calls = []
    provider_started = threading.Event()
    release_provider = threading.Event()

    def fake_fetch(start, end):
        calls.append((start, end))
        provider_started.set()
        assert release_provider.wait(timeout=5)
        return []

    cache.delete("econ_calendar")
    monkeypatch.setattr(news, "_fetch_economic_calendar", fake_fetch)

    def request_calendar():
        with app.test_client() as client:
            return client.get("/api/v1/news/economic-calendar")

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request_calendar)
            assert provider_started.wait(timeout=5)
            second = pool.submit(request_calendar)
            release_provider.set()
            responses = [first.result(timeout=5), second.result(timeout=5)]
    finally:
        cache.delete("econ_calendar")

    assert len(calls) == 1
    assert [response.status_code for response in responses] == [200, 200]
    assert all(response.get_json() == {"events": []} for response in responses)
