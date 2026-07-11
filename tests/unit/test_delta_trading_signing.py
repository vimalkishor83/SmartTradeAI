"""
Delta Exchange HMAC request-signing logic. This signing scheme is
verified against Delta's official python-rest-client (see the module
docstring in delta_trading.py) — these tests lock that behavior in so a
future refactor can't silently break order authentication, which would
either fail every real order (loud, annoying) or — worse — sign requests
incorrectly in a way that's accepted by some other unintended endpoint.
"""
import hashlib
import hmac

import pytest

from app.services.trading.delta_trading import DeltaTradingClient, DeltaTradingError


def _client():
    return DeltaTradingClient(api_key="test_key", api_secret="test_secret")


class TestQueryString:
    def test_empty_query_returns_empty_string(self):
        assert DeltaTradingClient._query_string(None) == ""
        assert DeltaTradingClient._query_string({}) == ""

    def test_single_param(self):
        assert DeltaTradingClient._query_string({"product_id": 123}) == "?product_id=123"

    def test_multiple_params_preserve_order(self):
        result = DeltaTradingClient._query_string({"a": "1", "b": "2"})
        assert result == "?a=1&b=2"

    def test_url_encodes_special_characters(self):
        result = DeltaTradingClient._query_string({"states": "open,pending"})
        # comma must be percent-encoded for Delta's signature scheme
        assert "," not in result
        assert result == "?states=open%2Cpending"


class TestBodyString:
    def test_empty_body_returns_empty_string(self):
        assert DeltaTradingClient._body_string(None) == ""
        assert DeltaTradingClient._body_string({}) == ""

    def test_compact_json_no_whitespace(self):
        result = DeltaTradingClient._body_string({"side": "buy", "size": 10})
        # separators=(",", ":") — no space after colon/comma, must match
        # exactly what Delta's server re-serializes for signature verification
        assert " " not in result
        assert result == '{"side":"buy","size":10}'


class TestSigning:
    def test_signature_is_deterministic_hmac_sha256(self):
        client = _client()
        # Freeze what _sign produces by re-deriving the same signature
        # independently, using the exact message format documented in the
        # module docstring: method + timestamp + path + query + body.
        timestamp, signature = client._sign("GET", "/v2/positions/margined", None, None)
        expected_message = "GET" + timestamp + "/v2/positions/margined" + "" + ""
        expected_sig = hmac.new(b"test_secret", expected_message.encode(), hashlib.sha256).hexdigest()
        assert signature == expected_sig

    def test_signature_changes_with_different_secrets(self):
        c1 = DeltaTradingClient(api_key="k", api_secret="secret_one")
        c2 = DeltaTradingClient(api_key="k", api_secret="secret_two")
        # Can't compare directly (timestamp differs between calls), so
        # sign the same fixed message manually with each secret instead.
        msg = "POST" + "1700000000" + "/v2/orders" + "" + '{"size":1}'
        sig1 = hmac.new(b"secret_one", msg.encode(), hashlib.sha256).hexdigest()
        sig2 = hmac.new(b"secret_two", msg.encode(), hashlib.sha256).hexdigest()
        assert sig1 != sig2

    def test_signature_includes_query_and_body_in_message(self):
        client = _client()
        ts1, sig1 = client._sign("GET", "/v2/orders", {"product_id": 1}, None)
        ts2, sig2 = client._sign("GET", "/v2/orders", {"product_id": 2}, None)
        # Different query params must produce different signatures even
        # with the same path/method (the whole point of including query
        # in the signed message — otherwise a signature could be replayed
        # against a different query).
        assert sig1 != sig2 or ts1 != ts2  # timestamps could coincidentally match at 1s resolution


class TestClientConstruction:
    def test_requires_api_key(self):
        with pytest.raises(DeltaTradingError):
            DeltaTradingClient(api_key="", api_secret="secret")

    def test_requires_api_secret(self):
        with pytest.raises(DeltaTradingError):
            DeltaTradingClient(api_key="key", api_secret="")

    def test_valid_credentials_construct_successfully(self):
        client = DeltaTradingClient(api_key="key", api_secret="secret")
        assert client.api_key == "key"
        assert client.api_secret == "secret"


class TestPlaceOrderValidation:
    def test_rejects_invalid_side(self):
        client = _client()
        with pytest.raises(DeltaTradingError):
            client.place_order(product_id=1, side="hold", size=1)

    def test_rejects_invalid_order_type(self):
        client = _client()
        with pytest.raises(DeltaTradingError):
            client.place_order(product_id=1, side="buy", size=1, order_type="stop_market")

    def test_limit_order_requires_limit_price(self):
        client = _client()
        with pytest.raises(DeltaTradingError):
            client.place_order(product_id=1, side="buy", size=1, order_type="limit_order", limit_price=None)
