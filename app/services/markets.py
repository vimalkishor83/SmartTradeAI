"""Canonical registry of tradeable markets — the single source of truth
Asset.MARKETS and APIConfig.MARKETS both derive from, replacing two
independently-hardcoded lists that had already drifted out of sync with
each other and with reality (2026-09-04 audit: Asset.MARKETS still said
"gold"/"silver" instead of "commodity" — what every real commodity asset
actually uses — and was missing "us_stock" entirely, despite APIConfig
and the broker registry already supporting it).

Adding a genuinely new market (options, currency, metals, broader
indices, etc.) starts here — one new entry — rather than touching
Asset.MARKETS, APIConfig.MARKETS, and every consumer of either
independently. Frontend templates still hardcode their own <option>
lists today (11 of them, per the same audit) rather than fetching this
registry — that consolidation is a separate, larger follow-up
deliberately not folded into this change, since it touches far more
surface area for comparatively less risk reduction than fixing the
two backend lists that had actually drifted.
"""

MARKETS = [
    {"key": "crypto",       "label": "Crypto"},
    {"key": "forex",        "label": "Forex"},
    {"key": "commodity",    "label": "Commodity"},
    {"key": "indian_stock", "label": "Indian Stocks"},
    {"key": "us_stock",     "label": "US Stocks"},
    {"key": "index",        "label": "Indices"},
]

MARKET_KEYS = [m["key"] for m in MARKETS]
MARKET_LABELS = {m["key"]: m["label"] for m in MARKETS}
