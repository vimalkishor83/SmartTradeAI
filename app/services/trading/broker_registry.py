"""
Registry of supported brokers a user can connect their own account to.

Each entry describes what credential FIELDS that broker needs (so the
frontend can render the right form) and whether a live trading CLIENT is
actually wired up yet (`trading_enabled`). Brokers with trading_enabled=False
still let a user save/encrypt their credentials — useful to have ready before
a client is built, and lets the UI show "Coming soon" rather than hiding the
broker entirely.

auth_type:
  "api_key_secret" — the two-field key/secret model already used for Delta.
  "api_key_secret_passphrase" — a third field some exchanges require
      (e.g. a trading PIN or passphrase, distinct from the account password).
  "oauth" — broker requires a browser login/consent flow (Zerodha Kite
      Connect, Upstox, Angel One's newer SDKs, etc.) — not a key/secret pair
      at all. No client is implemented for these yet; see module docstring.
"""
from __future__ import annotations

CATEGORY_CRYPTO = "crypto"
CATEGORY_STOCK = "indian_stock"
CATEGORY_FOREX = "forex"
CATEGORY_US_STOCK = "us_stock"

BROKERS: dict[str, dict] = {
    # ── Crypto exchanges — api_key + api_secret, well-documented public APIs ──
    "delta_exchange": {
        "label": "Delta Exchange India",
        "category": CATEGORY_CRYPTO,
        "auth_type": "api_key_secret",
        "trading_enabled": True,
        "docs_url": "https://www.delta.exchange/app/api-management",
        "help": "Create an API key with Trading permission in Delta Exchange → Account → API Keys.",
    },
    "binance": {
        "label": "Binance",
        "category": CATEGORY_CRYPTO,
        "auth_type": "api_key_secret",
        "trading_enabled": False,
        "docs_url": "https://www.binance.com/en/my/settings/api-management",
        "help": "Create an API key with Spot/Futures trading permission. Read-only market data already works without this.",
    },
    "coindcx": {
        "label": "CoinDCX",
        "category": CATEGORY_CRYPTO,
        "auth_type": "api_key_secret",
        "trading_enabled": False,
        "docs_url": "https://coindcx.com/api-dashboard",
        "help": "Generate an API key/secret from CoinDCX → API Dashboard.",
    },
    "bybit": {
        "label": "Bybit",
        "category": CATEGORY_CRYPTO,
        "auth_type": "api_key_secret",
        "trading_enabled": False,
        "docs_url": "https://www.bybit.com/app/user/api-management",
        "help": "Create an API key with Contract/Spot trading permission.",
    },
    "okx": {
        "label": "OKX",
        "category": CATEGORY_CRYPTO,
        "auth_type": "api_key_secret_passphrase",
        "trading_enabled": False,
        "docs_url": "https://www.okx.com/account/my-api",
        "help": "OKX requires an API key, secret, AND a separate passphrase you set when creating the key.",
    },
    "bitget": {
        "label": "Bitget",
        "category": CATEGORY_CRYPTO,
        "auth_type": "api_key_secret_passphrase",
        "trading_enabled": False,
        "docs_url": "https://www.bitget.com/en/account/newapi",
        "help": "Bitget requires an API key, secret, AND a passphrase set at key creation.",
    },
    "kucoin": {
        "label": "KuCoin",
        "category": CATEGORY_CRYPTO,
        "auth_type": "api_key_secret_passphrase",
        "trading_enabled": False,
        "docs_url": "https://www.kucoin.com/account/api",
        "help": "KuCoin requires an API key, secret, AND a passphrase set at key creation.",
    },

    # ── Indian stock brokers — mix of API-key and OAuth ──────────────────────
    "zerodha": {
        "label": "Zerodha (Kite Connect)",
        "category": CATEGORY_STOCK,
        "auth_type": "oauth",
        "trading_enabled": False,
        "docs_url": "https://kite.trade/",
        "help": "Zerodha uses a browser login/consent flow (Kite Connect), not a static key/secret. Coming soon.",
    },
    "upstox": {
        "label": "Upstox",
        "category": CATEGORY_STOCK,
        "auth_type": "oauth",
        "trading_enabled": False,
        "docs_url": "https://upstox.com/developer/api-documentation/",
        "help": "Upstox uses OAuth2 login. Coming soon.",
    },
    "angel_one": {
        "label": "Angel One (SmartAPI)",
        "category": CATEGORY_STOCK,
        "auth_type": "api_key_secret",
        "trading_enabled": False,
        "docs_url": "https://smartapi.angelbroking.com/",
        "help": "Create a SmartAPI key from Angel One's developer portal.",
    },
    "fyers": {
        "label": "Fyers",
        "category": CATEGORY_STOCK,
        "auth_type": "oauth",
        "trading_enabled": False,
        "docs_url": "https://myapi.fyers.in/",
        "help": "Fyers uses an OAuth login flow. Coming soon.",
    },
    "dhan": {
        "label": "Dhan",
        "category": CATEGORY_STOCK,
        "auth_type": "api_key_secret",
        "trading_enabled": False,
        "docs_url": "https://dhanhq.co/docs/",
        "help": "Generate an access token from Dhan's DhanHQ developer console.",
    },
    "kotak": {
        "label": "Kotak Securities (Neo)",
        "category": CATEGORY_STOCK,
        "auth_type": "oauth",
        "trading_enabled": False,
        "docs_url": "https://tradeapi.kotaksecurities.com/",
        "help": "Kotak Neo uses a multi-step OAuth + TOTP login flow. Coming soon.",
    },
    "icici_direct": {
        "label": "ICICI Direct (Breeze)",
        "category": CATEGORY_STOCK,
        "auth_type": "api_key_secret",
        "trading_enabled": False,
        "docs_url": "https://api.icicidirect.com/",
        "help": "Create an API key/secret from ICICI Direct's Breeze API portal.",
    },
    "groww": {
        "label": "Groww",
        "category": CATEGORY_STOCK,
        "auth_type": "api_key_secret",
        "trading_enabled": False,
        "docs_url": "https://groww.in/trade-api/docs",
        "help": "Generate an API key/secret from Groww's Trade API dashboard.",
    },

    # ── Forex / CFD brokers ───────────────────────────────────────────────────
    "oanda": {
        "label": "OANDA",
        "category": CATEGORY_FOREX,
        "auth_type": "api_key_secret",
        "trading_enabled": False,
        "docs_url": "https://developer.oanda.com/",
        "help": "OANDA uses a single API token (enter it as the API key; leave secret blank).",
    },
    "xm": {
        "label": "XM",
        "category": CATEGORY_FOREX,
        "auth_type": "api_key_secret",
        "trading_enabled": False,
        "docs_url": "https://www.xm.com/",
        "help": "XM does not publish a public trading API — MT4/MT5 accounts connect via a bridge, not a key/secret. Saved here for future MT4/5 bridge integration; trading is not yet available.",
    },

    # ── US stock / multi-asset brokers ────────────────────────────────────────
    "alpaca": {
        "label": "Alpaca",
        "category": CATEGORY_US_STOCK,
        "auth_type": "api_key_secret",
        "trading_enabled": False,
        "docs_url": "https://alpaca.markets/docs/",
        "help": "Create an API key/secret from Alpaca's dashboard (paper or live).",
    },
    "interactive_brokers": {
        "label": "Interactive Brokers",
        "category": CATEGORY_US_STOCK,
        "auth_type": "oauth",
        "trading_enabled": False,
        "docs_url": "https://www.interactivebrokers.com/api/doc.html",
        "help": "IBKR requires their Client Portal Gateway running locally, not a static key/secret. Coming soon.",
    },
    "tradier": {
        "label": "Tradier",
        "category": CATEGORY_US_STOCK,
        "auth_type": "api_key_secret",
        "trading_enabled": False,
        "docs_url": "https://documentation.tradier.com/",
        "help": "Create an access token from Tradier's developer dashboard (enter as API key; leave secret blank).",
    },
}


def get_broker(provider: str) -> dict | None:
    return BROKERS.get(provider)


def list_brokers() -> list[dict]:
    return [{"provider": key, **meta} for key, meta in BROKERS.items()]


def required_fields(provider: str) -> list[str]:
    """Which credential fields this broker's auth_type needs."""
    meta = BROKERS.get(provider)
    if not meta:
        return []
    auth_type = meta["auth_type"]
    if auth_type == "api_key_secret":
        return ["api_key", "api_secret"]
    if auth_type == "api_key_secret_passphrase":
        return ["api_key", "api_secret", "passphrase"]
    if auth_type == "oauth":
        return []  # handled via a browser redirect flow, not form fields
    return []
