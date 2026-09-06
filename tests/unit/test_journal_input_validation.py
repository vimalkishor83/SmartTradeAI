import pytest

from app.api.v1.journal import (
    MAX_JOURNAL_PRICE,
    MAX_JOURNAL_QUANTITY,
    _optional_asset_id,
    _optional_number,
    _validate_entry_payload,
)


def test_journal_payload_requires_object_and_normalizes_valid_values():
    with pytest.raises(ValueError, match="request body must be a JSON object"):
        _validate_entry_payload([])

    result = _validate_entry_payload({
        "trade_date": "2026-09-06",
        "direction": "sell",
        "timeframe": "1h",
        "entry_price": "100",
        "exit_price": 95,
        "quantity": 2,
        "setup_tags": [" breakout "],
    })

    assert result["direction"] == "SELL"
    assert result["entry_price"] == 100.0
    assert result["setup_tags"] == ["breakout"]


def test_journal_payload_rejects_unsafe_or_unbounded_values():
    with pytest.raises(ValueError):
        _optional_number(float("nan"), "pnl_amount")
    with pytest.raises(ValueError):
        _optional_number(MAX_JOURNAL_PRICE + 1, "entry_price", maximum=MAX_JOURNAL_PRICE)
    with pytest.raises(ValueError):
        _optional_number(MAX_JOURNAL_QUANTITY + 1, "quantity", maximum=MAX_JOURNAL_QUANTITY)
    with pytest.raises(ValueError):
        _validate_entry_payload({"direction": "SHORT"})
    with pytest.raises(ValueError):
        _validate_entry_payload({"screenshot_url": "javascript:alert(1)"})


def test_journal_asset_id_accepts_positive_ids_only():
    assert _optional_asset_id("12") == 12
    assert _optional_asset_id(None) is None
    with pytest.raises(ValueError):
        _optional_asset_id(True)
    with pytest.raises(ValueError):
        _optional_asset_id("12.5")
