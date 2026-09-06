"""Regression coverage for portfolio rows with incomplete legacy dates."""

from app.models.portfolio import PortfolioItem


def test_portfolio_item_serialization_tolerates_missing_buy_date():
    item = PortfolioItem(quantity=2, buy_price=100, current_price=110, buy_date=None)

    payload = item.to_dict()

    assert payload["holding_days"] is None
    assert payload["current_value"] == 220
    assert payload["pnl"] == 20

