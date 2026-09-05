"""Regression coverage for batched news ingestion and feed deduplication."""

from datetime import datetime


def test_fetch_news_deduplicates_provider_batch_without_rechecking_each_url(
    app, monkeypatch,
):
    from app.extensions import db
    from app.models.asset import Asset
    from app.models.news import News

    with app.app_context():
        db.session.add(Asset(
            symbol="NEWSASSET", name="News Asset", market="crypto", is_active=True,
        ))
        db.session.add(News(
            title="Existing article",
            url="https://example.test/existing",
            published_at=datetime.utcnow(),
        ))
        db.session.commit()

    items = [
        {
            "title": "Existing article again",
            "url": "https://example.test/existing",
        },
        {
            "title": "New article",
            "url": "https://example.test/new",
            "related_assets": ["NEWSASSET"],
        },
        {
            "title": "New article duplicate",
            "url": "https://example.test/new",
        },
        {"title": "No URL article"},
    ]

    from app.services.news import fetcher
    from app.tasks.data_tasks import fetch_news

    monkeypatch.setattr(
        fetcher, "fetch_news_for_symbols", lambda _symbols: items,
    )
    fetch_news(app)

    with app.app_context():
        rows = News.query.order_by(News.url).all()
        assert [row.url for row in rows] == [
            "https://example.test/existing",
            "https://example.test/new",
        ]
        assert rows[1].related_assets == ["NEWSASSET"]
