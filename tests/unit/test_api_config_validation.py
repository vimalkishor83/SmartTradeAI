"""Boundary tests for admin API-configuration payload validation."""

from types import SimpleNamespace

import pytest

from app.services.api_config_validation import (
    APIConfigValidationError,
    validate_api_config_payload,
)


def test_create_payload_is_normalized_without_changing_valid_values():
    payload = validate_api_config_payload({
        "name": "  Binance Main  ",
        "provider": "binance",
        "market": "crypto",
        "base_url": " https://api.binance.com ",
        "rate_limit": "120",
        "refresh_interval": 60,
        "is_default": "false",
    })

    assert payload["name"] == "Binance Main"
    assert payload["base_url"] == "https://api.binance.com"
    assert payload["rate_limit"] == 120
    assert payload["is_default"] is False


@pytest.mark.parametrize("payload", [
    None,
    [],
    {"name": "Only name"},
    {"name": "Config", "provider": "binance", "market": "not-a-market"},
    {"name": "Config", "provider": "groq", "market": "crypto"},
])
def test_create_rejects_malformed_or_incompatible_payloads(payload):
    with pytest.raises(APIConfigValidationError):
        validate_api_config_payload(payload)


@pytest.mark.parametrize("field,value", [
    ("rate_limit", True),
    ("refresh_interval", 0),
    ("priority", "1.5"),
    ("is_active", "maybe"),
    ("auth_type", "password"),
])
def test_create_rejects_ambiguous_field_values(field, value):
    payload = {"name": "Config", "provider": "binance", "market": "crypto", field: value}

    with pytest.raises(APIConfigValidationError):
        validate_api_config_payload(payload)


def test_update_rejects_market_change_that_would_leave_provider_incompatible():
    existing = SimpleNamespace(market="crypto", provider="binance")

    with pytest.raises(APIConfigValidationError, match="provider is not supported"):
        validate_api_config_payload({"market": "ai"}, existing=existing)


def test_update_allows_provider_change_for_the_final_market():
    existing = SimpleNamespace(market="crypto", provider="binance")

    payload = validate_api_config_payload(
        {"market": "ai", "provider": "groq", "is_active": "0"},
        existing=existing,
    )

    assert payload == {"market": "ai", "provider": "groq", "is_active": False}


def test_update_accepts_partial_payload_but_still_normalizes_text():
    existing = SimpleNamespace(market="crypto", provider="binance")

    payload = validate_api_config_payload({"name": "  Renamed  "}, existing=existing)

    assert payload == {"name": "Renamed"}
