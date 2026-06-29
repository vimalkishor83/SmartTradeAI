"""
Pluggable market data fetcher — 100% free APIs, no keys required.
  • Crypto  → Binance public REST (no API key)
  • Forex   → Yahoo Finance via yfinance (free)
  • Gold/Silver → Yahoo Finance futures (GC=F, SI=F)
  • Indian Stocks/Indices → Yahoo Finance (.NS / ^NSEI etc.)
"""
from __future__ import annotations
import logging
import requests
import pandas as pd

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False
    logging.getLogger(__name__).warning("yfinance not installed — Yahoo data unavailable. Run: pip install yfinance")

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Binance (crypto) — completely public, no key needed
# ─────────────────────────────────────────────────────────
class BinanceFetcher:
    BASE = "https://api.binance.com/api/v3"
    INTERVAL = {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"4h","1d":"1d"}

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame | None:
        interval = self.INTERVAL.get(timeframe, "1h")
        try:
            resp = requests.get(
                f"{self.BASE}/klines",
                params={"symbol": symbol, "interval": interval, "limit": min(limit, 1000)},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            df = pd.DataFrame(data, columns=[
                "timestamp","open","high","low","close","volume",
                "close_time","quote_volume","trades","taker_buy_base","taker_buy_quote","ignore",
            ])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            for col in ["open","high","low","close","volume"]:
                df[col] = df[col].astype(float)
            return df[["timestamp","open","high","low","close","volume"]].set_index("timestamp")
        except Exception as e:
            logger.warning(f"Binance OHLCV error {symbol}/{timeframe}: {e}")
            return None

    def fetch_ticker(self, symbol: str) -> dict | None:
        try:
            resp = requests.get(f"{self.BASE}/ticker/24hr", params={"symbol": symbol}, timeout=5)
            resp.raise_for_status()
            d = resp.json()
            return {
                "symbol":     symbol,
                "price":      float(d["lastPrice"]),
                "change_pct": float(d["priceChangePercent"]),
                "volume":     float(d["volume"]),
                "high":       float(d["highPrice"]),
                "low":        float(d["lowPrice"]),
            }
        except Exception as e:
            logger.warning(f"Binance ticker error {symbol}: {e}")
            return None


# ─────────────────────────────────────────────────────────
# Yahoo Finance — free, no key needed
# ─────────────────────────────────────────────────────────
class YahooFetcher:
    # Map our symbols → Yahoo Finance symbols
    SYMBOL_MAP = {
        # Indices
        "NIFTY50":    "^NSEI",
        "BANKNIFTY":  "^NSEBANK",
        "SENSEX":     "^BSESN",
        "FINNIFTY":   "NIFTY_FIN_SERVICE.NS",
        "MIDCPNIFTY": "^NSMIDCP",
        # Commodities
        "XAUUSD": "GC=F",
        "XAGUSD": "SI=F",
        "CLUSD":  "CL=F",
        # Forex
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "USDJPY": "USDJPY=X",
        "AUDUSD": "AUDUSD=X",
        "USDINR": "INR=X",
    }

    # NSE-listed stocks
    NSE_STOCKS = {
        "RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK","SBIN",
        "WIPRO","ADANIENT","BAJFINANCE","KOTAKBANK","HINDUNILVR",
        "LT","ITC","AXISBANK","MARUTI",
    }

    TF_INTERVAL = {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"60m","4h":"1h","1d":"1d"}
    TF_PERIOD   = {"1m":"7d","5m":"60d","15m":"60d","30m":"60d","1h":"2y","4h":"2y","1d":"5y"}

    def _yahoo_symbol(self, symbol: str) -> str:
        if symbol in self.SYMBOL_MAP:
            return self.SYMBOL_MAP[symbol]
        if symbol in self.NSE_STOCKS:
            return f"{symbol}.NS"
        # BSE stocks
        if symbol.endswith(".BO") or symbol.endswith(".NS"):
            return symbol
        return symbol

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300) -> pd.DataFrame | None:
        if not _YF_AVAILABLE:
            logger.debug(f"yfinance unavailable, skipping {symbol}")
            return None
        try:
            yf_symbol = self._yahoo_symbol(symbol)
            interval  = self.TF_INTERVAL.get(timeframe, "1d")
            period    = self.TF_PERIOD.get(timeframe, "1y")

            df = yf.download(
                yf_symbol,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
                threads=False,
            )

            if df is None or df.empty:
                logger.warning(f"Yahoo empty data for {yf_symbol}")
                return None

            # Flatten multi-level columns if present (yfinance 0.2+)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df.columns = [c.lower() for c in df.columns]
            needed = [c for c in ["open","high","low","close","volume"] if c in df.columns]
            df = df[needed].dropna()
            if "volume" not in df.columns:
                df["volume"] = 0.0

            return df.tail(limit)
        except Exception as e:
            logger.debug(f"Yahoo OHLCV error {symbol}/{timeframe}: {e}")
            return None


# ─────────────────────────────────────────────────────────
# Unified fetcher
# ─────────────────────────────────────────────────────────
class MarketDataFetcher:
    def __init__(self):
        self.binance = BinanceFetcher()
        self.yahoo   = YahooFetcher()

    def fetch(self, asset, timeframe: str, limit: int = 300) -> pd.DataFrame | None:
        if asset.data_source == "binance":
            return self.binance.fetch_ohlcv(asset.symbol, timeframe, limit)
        return self.yahoo.fetch_ohlcv(asset.symbol, timeframe, limit)

    def fetch_ticker(self, asset) -> dict | None:
        if asset.data_source == "binance":
            return self.binance.fetch_ticker(asset.symbol)
        # Yahoo quick price
        if not _YF_AVAILABLE:
            return None
        try:
            yf_symbol = self.yahoo._yahoo_symbol(asset.symbol)
            info = yf.Ticker(yf_symbol).fast_info  # noqa: F821 — yf imported at top
            price = getattr(info, 'last_price', None) or getattr(info, 'regularMarketPrice', None)
            if price:
                return {"symbol": asset.symbol, "price": float(price), "change_pct": 0.0}
        except Exception:
            pass
        return None


market_fetcher = MarketDataFetcher()
