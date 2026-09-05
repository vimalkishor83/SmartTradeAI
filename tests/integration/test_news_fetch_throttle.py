"""Regression coverage for the empty-news background-fetch throttle."""


def test_empty_news_requests_start_only_one_background_fetch(
    app, client, monkeypatch,
):
    from types import SimpleNamespace

    from app.api.v1 import news
    from app.extensions import cache

    started = []

    class _FakeThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            started.append(self)

    cache.delete(news._NEWS_FETCH_MARKER)
    # Replace the route module's import rather than threading.Thread itself;
    # Flask-Limiter uses threading.Timer internally during request handling.
    monkeypatch.setattr(news, "threading", SimpleNamespace(Thread=_FakeThread))

    try:
        first = client.get("/api/v1/news/?page=1")
        second = client.get("/api/v1/news/?page=1")
    finally:
        cache.delete(news._NEWS_FETCH_MARKER)

    assert first.status_code == second.status_code == 200
    assert first.get_json()["fetching"] is True
    assert second.get_json()["fetching"] is True
    assert len(started) == 1
    assert started[0].daemon is True
