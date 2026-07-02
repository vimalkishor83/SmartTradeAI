"""
Delta Exchange India authenticated trading client.

Implements the HMAC-SHA256 request signing scheme exactly as used by
Delta's official python-rest-client (verified against the real source at
https://github.com/delta-exchange/python-rest-client), NOT guessed from
docs:

  signature_string = method + timestamp + path + query_string + body_string
  signature = HMAC-SHA256(api_secret, signature_string).hexdigest()
  headers   = {api-key, timestamp, signature, Content-Type, User-Agent}
  timestamp = unix seconds; server rejects requests signed >5s ago

This client is deliberately separate from services/data/fetcher.py's
DeltaExchangeFetcher, which only calls Delta's public (unauthenticated)
market-data endpoints. This module is exclusively for private,
order-placing, real-money endpoints and requires a configured API
key/secret with trading permission.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.parse

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.india.delta.exchange"


class DeltaTradingError(Exception):
    """Raised for any failed/rejected trading API call — always caught and
    surfaced as a clean error message, never allowed to crash a request."""
    def __init__(self, message: str, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class DeltaTradingClient:
    def __init__(self, api_key: str, api_secret: str):
        if not api_key or not api_secret:
            raise DeltaTradingError("Delta Exchange API key/secret not configured")
        self.api_key = api_key
        self.api_secret = api_secret

    # ── Signing (verified against official client) ──────────────────────
    @staticmethod
    def _query_string(query: dict | None) -> str:
        if not query:
            return ""
        parts = [f"{k}={urllib.parse.quote_plus(str(v))}" for k, v in query.items()]
        return "?" + "&".join(parts)

    @staticmethod
    def _body_string(body: dict | None) -> str:
        if not body:
            return ""
        return json.dumps(body, separators=(",", ":"))

    def _sign(self, method: str, path: str, query: dict | None, body: dict | None) -> tuple[str, str]:
        timestamp = str(int(time.time()))
        message = method + timestamp + path + self._query_string(query) + self._body_string(body)
        signature = hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        return timestamp, signature

    def _request(self, method: str, path: str, query: dict | None = None,
                 body: dict | None = None, timeout: int = 10) -> dict:
        timestamp, signature = self._sign(method, path, query, body)
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
            "User-Agent": "smarttradeai-delta-client-v1",
        }
        url = BASE_URL + path
        try:
            resp = requests.request(
                method, url, params=query,
                data=self._body_string(body) if body else None,
                headers=headers, timeout=timeout,
            )
        except requests.RequestException as e:
            raise DeltaTradingError(f"Network error contacting Delta Exchange: {e}")

        try:
            payload = resp.json()
        except ValueError:
            payload = {}

        if not resp.ok or payload.get("success") is False:
            err = payload.get("error", {})
            msg = err.get("code") or err.get("message") or f"HTTP {resp.status_code}"
            raise DeltaTradingError(str(msg), status_code=resp.status_code, payload=payload)

        return payload.get("result", payload)

    # ── Public-facing trading operations ─────────────────────────────────
    def get_product_id(self, delta_symbol: str) -> int:
        """Resolve a Delta symbol (e.g. BTCUSD) to its numeric product_id.
        Uses the public products endpoint — no auth needed for this lookup."""
        resp = requests.get(f"{BASE_URL}/v2/products/{delta_symbol}", timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success"):
            raise DeltaTradingError(f"Unknown Delta product: {delta_symbol}")
        return payload["result"]["id"]

    def place_order(self, product_id: int, side: str, size: int, order_type: str = "limit_order",
                     limit_price: str | None = None, stop_price: str | None = None,
                     time_in_force: str | None = None, reduce_only: bool = False,
                     post_only: bool = False, client_order_id: str | None = None) -> dict:
        if side not in ("buy", "sell"):
            raise DeltaTradingError("side must be 'buy' or 'sell'")
        if order_type not in ("limit_order", "market_order"):
            raise DeltaTradingError("order_type must be 'limit_order' or 'market_order'")

        order = {
            "product_id": product_id,
            "size": int(size),
            "side": side,
            "order_type": order_type,
            "post_only": "true" if post_only else "false",
            "reduce_only": "true" if reduce_only else "false",
        }
        if order_type == "limit_order":
            if not limit_price:
                raise DeltaTradingError("limit_price is required for limit orders")
            order["limit_price"] = str(limit_price)
        if stop_price:
            order["stop_price"] = str(stop_price)
            order["stop_order_type"] = "stop_loss_order"
        if time_in_force:
            order["time_in_force"] = time_in_force
        if client_order_id:
            order["client_order_id"] = client_order_id

        return self._request("POST", "/v2/orders", body=order)

    def cancel_order(self, order_id: int, product_id: int) -> dict:
        return self._request("DELETE", "/v2/orders", body={"id": order_id, "product_id": product_id})

    def get_open_orders(self, product_ids: str | None = None) -> list:
        query = {"states": "open,pending"}
        if product_ids:
            query["product_ids"] = product_ids
        return self._request("GET", "/v2/orders", query=query)

    def get_order_history(self, page_size: int = 50, after: str | None = None) -> list:
        query = {"page_size": page_size}
        if after:
            query["after"] = after
        return self._request("GET", "/v2/orders/history", query=query)

    def get_positions(self) -> list:
        return self._request("GET", "/v2/positions/margined", query={})

    def get_balances(self) -> list:
        return self._request("GET", "/v2/wallet/balances")

    def set_leverage(self, product_id: int, leverage: int) -> dict:
        return self._request("POST", f"/v2/products/{product_id}/orders/leverage",
                              body={"leverage": leverage})


def get_configured_client() -> DeltaTradingClient:
    """Load the active Delta Exchange trading APIConfig from the DB and
    build a client. Raises DeltaTradingError with a clear message if none
    is configured — callers surface this directly to the UI rather than a
    generic 500."""
    from app.models.api_config import APIConfig

    cfg = APIConfig.query.filter_by(
        provider="delta_exchange", market="crypto", is_active=True
    ).order_by(APIConfig.is_default.desc(), APIConfig.priority.desc()).first()

    if not cfg:
        raise DeltaTradingError(
            "No Delta Exchange API config found. Add one in Admin → API Configs."
        )

    api_key = cfg.get_api_key()
    api_secret = cfg.get_api_secret()
    if not api_key or not api_secret:
        raise DeltaTradingError(
            "Delta Exchange API config is missing a key/secret with trading "
            "permission. Add your real credentials in Admin → API Configs."
        )

    return DeltaTradingClient(api_key, api_secret)
