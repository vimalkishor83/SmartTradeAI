import pytest


@pytest.mark.parametrize("sentiment", ["bullish", "all", "<script>", "positive,negative"])
def test_news_rejects_unknown_sentiment_filters(client, sentiment):
    response = client.get("/api/v1/news/", query_string={"sentiment": sentiment})

    assert response.status_code == 400
    assert "sentiment must be one of" in response.get_json()["error"]


def test_news_normalizes_supported_sentiment_filter(app, client):
    with app.app_context():
        from app.extensions import db
        from app.models.news import News

        db.session.add_all([
            News(title="Positive item", sentiment="positive"),
            News(title="Negative item", sentiment="negative"),
        ])
        db.session.commit()

    response = client.get("/api/v1/news/", query_string={"sentiment": " POSITIVE "})

    assert response.status_code == 200
    assert response.get_json()["total"] == 1
    assert response.get_json()["news"][0]["sentiment"] == "positive"

