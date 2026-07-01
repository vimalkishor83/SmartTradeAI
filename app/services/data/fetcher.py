"""
Pluggable market data fetcher — 100% free APIs, no keys required.
  • Crypto  → Binance public REST (no API key)
  • Forex   → Yahoo Finance via yfinance (free)
  • Gold/Silver → Yahoo Finance futures (GC=F, SI=F)
  • Indian Stocks/Indices → Yahoo Finance (.NS / ^NSEI etc.)
"""
from __future__ import annotations
import logging
import time
import threading
from functools import wraps
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False
    logging.getLogger(__name__).warning("yfinance not installed — Yahoo data unavailable. Run: pip install yfinance")

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Retry decorator for transient network failures
# ─────────────────────────────────────────────────────────
def _retry(max_attempts: int = 3, backoff: float = 1.5):
    """Retry on any exception with exponential backoff. Returns None on final failure."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        logger.warning(f"{fn.__name__} failed after {max_attempts} attempts: {e}")
                        return None
                    time.sleep(backoff ** attempt)
        return wrapper
    return decorator


# ─────────────────────────────────────────────────────────
# Circuit breaker — stops hammering a source that is down
# ─────────────────────────────────────────────────────────
class _CircuitBreaker:
    """
    Open (block) after `failure_threshold` consecutive failures.
    Half-open (allow one probe) after `recovery_timeout` seconds.
    """
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: int = 120):
        self._name             = name
        self._threshold        = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failures         = 0
        self._opened_at: float = 0.0
        self._lock             = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if self._failures < self._threshold:
                return True
            if time.time() - self._opened_at >= self._recovery_timeout:
                self._failures = 0   # reset — probe allowed
                return True
            return False

    def success(self):
        with self._lock:
            self._failures = 0

    def failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._opened_at = time.time()
                logger.warning(f"Circuit breaker OPEN for {self._name} after {self._failures} failures")


_breaker_binance = _CircuitBreaker("binance")
_breaker_yahoo   = _CircuitBreaker("yahoo")


# ─────────────────────────────────────────────────────────
# In-process OHLCV cache (avoids redundant network hits)
# ─────────────────────────────────────────────────────────
class _OHLCVCache:
    """Thread-safe in-memory cache with per-key TTL."""
    def __init__(self):
        self._store: dict[str, tuple[pd.DataFrame, float]] = {}
        self._lock  = threading.Lock()

    # TTL by timeframe — shorter TFs need fresher data
    _TTL = {"1m":30,"5m":60,"15m":90,"30m":120,"1h":180,"2h":240,"4h":300,"1d":600}

    def get(self, key: str) -> pd.DataFrame | None:
        with self._lock:
            entry = self._store.get(key)
            if entry and time.time() - entry[1] < self._TTL.get(key.rsplit("_",1)[-1], 180):
                return entry[0]
        return None

    def set(self, key: str, df: pd.DataFrame):
        with self._lock:
            self._store[key] = (df, time.time())

    def clear(self):
        with self._lock:
            self._store.clear()


_cache = _OHLCVCache()


# ─────────────────────────────────────────────────────────
# Binance (crypto) — completely public, no key needed
# ─────────────────────────────────────────────────────────
class BinanceFetcher:
    BASE = "https://api.binance.com/api/v3"
    INTERVAL = {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"1h","2h":"2h","4h":"4h","1d":"1d"}

    @_retry(max_attempts=3, backoff=1.5)
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 220) -> pd.DataFrame | None:
        cache_key = f"{symbol}_{timeframe}"
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

        if not _breaker_binance.allow():
            return None   # circuit open — avoid hammering a down service

        try:
            interval = self.INTERVAL.get(timeframe, "1h")
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
            df = df[["timestamp","open","high","low","close","volume"]].set_index("timestamp")
            _cache.set(cache_key, df)
            _breaker_binance.success()
            return df
        except Exception as e:
            _breaker_binance.failure()
            raise   # re-raise so @_retry can catch it

    def fetch_ticker(self, symbol: str) -> dict | None:
        if not _breaker_binance.allow():
            return None
        try:
            resp = requests.get(f"{self.BASE}/ticker/24hr", params={"symbol": symbol}, timeout=5)
            resp.raise_for_status()
            d = resp.json()
            _breaker_binance.success()
            return {
                "symbol":     symbol,
                "price":      float(d["lastPrice"]),
                "change_pct": float(d["priceChangePercent"]),
                "volume":     float(d["volume"]),
                "high":       float(d["highPrice"]),
                "low":        float(d["lowPrice"]),
            }
        except Exception as e:
            _breaker_binance.failure()
            logger.warning(f"Binance ticker error {symbol}: {e}")
            return None


# ─────────────────────────────────────────────────────────
# Yahoo Finance — free, no key needed
# ─────────────────────────────────────────────────────────
class YahooFetcher:
    SYMBOL_MAP = {
        "NIFTY50":    "^NSEI",
        "BANKNIFTY":  "^NSEBANK",
        "SENSEX":     "^BSESN",
        "FINNIFTY":   "NIFTY_FIN_SERVICE.NS",
        "MIDCPNIFTY": "^NSMIDCP",
        "XAUUSD": "GC=F",
        "XAGUSD": "SI=F",
        "CLUSD":  "CL=F",
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "USDJPY": "USDJPY=X",
        "AUDUSD": "AUDUSD=X",
        "USDINR": "INR=X",
    }

    NSE_STOCKS = {
        "RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK","SBIN",
        "WIPRO","ADANIENT","BAJFINANCE","KOTAKBANK","HINDUNILVR",
        "LT","ITC","AXISBANK","MARUTI",
    }

    TF_INTERVAL = {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"60m","2h":"90m","4h":"1h","1d":"1d"}
    TF_PERIOD   = {"1m":"7d","5m":"60d","15m":"60d","30m":"60d","1h":"2y","2h":"2y","4h":"2y","1d":"5y"}

    def _yahoo_symbol(self, symbol: str) -> str:
        if symbol in self.SYMBOL_MAP:
            return self.SYMBOL_MAP[symbol]
        if symbol in self.NSE_STOCKS:
            return f"{symbol}.NS"
        if symbol.endswith(".BO") or symbol.endswith(".NS"):
            return symbol
        return symbol

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 220) -> pd.DataFrame | None:
        if not _YF_AVAILABLE:
            return None
        if not _breaker_yahoo.allow():
            return None

        cache_key = f"{symbol}_{timeframe}"
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

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
                return None

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df.columns = [c.lower() for c in df.columns]
            needed = [c for c in ["open","high","low","close","volume"] if c in df.columns]
            df = df[needed].dropna()
            if "volume" not in df.columns:
                df["volume"] = 0.0

            df = df.tail(limit)
            _cache.set(cache_key, df)
            _breaker_yahoo.success()
            return df
        except Exception as e:
            _breaker_yahoo.failure()
            logger.debug(f"Yahoo OHLCV error {symbol}/{timeframe}: {e}")
            return None

    def fetch_ohlcv_batch(self, symbols: list[str], timeframe: str, limit: int = 220) -> dict[str, pd.DataFrame]:
        """Fetch multiple Yahoo symbols in a single download call (much faster than one-by-one)."""
        if not _YF_AVAILABLE or not symbols:
            return {}

        # Check cache first — only fetch what's missing
        result: dict[str, pd.DataFrame] = {}
        to_fetch_sym: list[str]  = []   # our symbols
        to_fetch_yf:  list[str]  = []   # yahoo symbols

        for sym in symbols:
            cached = _cache.get(f"{sym}_{timeframe}")
            if cached is not None:
                result[sym] = cached
            else:
                to_fetch_sym.append(sym)
                to_fetch_yf.append(self._yahoo_symbol(sym))

        if not to_fetch_yf:
            return result

        interval = self.TF_INTERVAL.get(timeframe, "1d")
        period   = self.TF_PERIOD.get(timeframe, "1y")

        try:
            raw = yf.download(
                " ".join(to_fetch_yf),
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
                threads=True,   # yfinance internal threading for batch
                group_by="ticker",
            )
            if raw is None or raw.empty:
                return result

            # Build reverse map: yahoo symbol → our symbol
            rev = {yf_sym: our_sym for our_sym, yf_sym in zip(to_fetch_sym, to_fetch_yf)}

            # Single-ticker download has flat columns; multi-ticker has MultiIndex
            if len(to_fetch_yf) == 1:
                yf_sym = to_fetch_yf[0]
                our    = rev[yf_sym]
                df = raw.copy()
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df.columns = [c.lower() for c in df.columns]
                needed = [c for c in ["open","high","low","close","volume"] if c in df.columns]
                df = df[needed].dropna().tail(limit)
                if "volume" not in df.columns:
                    df["volume"] = 0.0
                _cache.set(f"{our}_{timeframe}", df)
                result[our] = df
            else:
                for yf_sym in to_fetch_yf:
                    our = rev[yf_sym]
                    try:
                        df = raw[yf_sym].copy() if yf_sym in raw.columns.get_level_values(0) else pd.DataFrame()
                        if df.empty:
                            continue
                        df.columns = [c.lower() for c in df.columns]
                        needed = [c for c in ["open","high","low","close","volume"] if c in df.columns]
                        df = df[needed].dropna().tail(limit)
                        if "volume" not in df.columns:
                            df["volume"] = 0.0
                        _cache.set(f"{our}_{timeframe}", df)
                        result[our] = df
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Yahoo batch error {timeframe}: {e}")

        return result


# ─────────────────────────────────────────────────────────
# Unified fetcher
# ─────────────────────────────────────────────────────────
class MarketDataFetcher:
    def __init__(self):
        self.binance = BinanceFetcher()
        self.yahoo   = YahooFetcher()

    def fetch(self, asset, timeframe: str, limit: int = 220) -> pd.DataFrame | None:
        if asset.data_source == "binance":
            return self.binance.fetch_ohlcv(asset.symbol, timeframe, limit)
        return self.yahoo.fetch_ohlcv(asset.symbol, timeframe, limit)

    def fetch_ticker(self, asset) -> dict | None:
        if asset.data_source == "binance":
            return self.binance.fetch_ticker(asset.symbol)
        if not _YF_AVAILABLE:
            return None
        try:
            yf_symbol = self.yahoo._yahoo_symbol(asset.symbol)
            info  = yf.Ticker(yf_symbol).fast_info
            price = getattr(info, 'last_price', None) or getattr(info, 'regularMarketPrice', None)
            if price:
                return {"symbol": asset.symbol, "price": float(price), "change_pct": 0.0}
        except Exception:
            pass
        return None

    def fetch_many(self, assets: list, timeframes: list[str], limit: int = 220) -> dict[str, dict[str, pd.DataFrame]]:
        """
        Fetch OHLCV for multiple assets × timeframes in parallel.
        Returns {symbol: {timeframe: DataFrame}}
        """
        # Separate by data source
        binance_assets = [a for a in assets if a.data_source == "binance"]
        yahoo_assets   = [a for a in assets if a.data_source != "binance"]

        results: dict[str, dict[str, pd.DataFrame]] = {a.symbol: {} for a in assets}

        # ── Binance: parallel per (symbol, tf) ──────────────────
        def _binance_fetch(asset, tf):
            return asset.symbol, tf, self.binance.fetch_ohlcv(asset.symbol, tf, limit)

        if binance_assets:
            with ThreadPoolExecutor(max_workers=min(20, len(binance_assets) * len(timeframes))) as ex:
                futures = {ex.submit(_binance_fetch, a, tf): (a.symbol, tf)
                           for a in binance_assets for tf in timeframes}
                for fut in as_completed(futures):
                    sym, tf, df = fut.result()
                    if df is not None:
                        results[sym][tf] = df

        # ── Yahoo: batch per timeframe (1 HTTP call per TF) ─────
        if yahoo_assets:
            yahoo_syms = [a.symbol for a in yahoo_assets]
            for tf in timeframes:
                batch = self.yahoo.fetch_ohlcv_batch(yahoo_syms, tf, limit)
                for sym, df in batch.items():
                    results[sym][tf] = df

        return results


market_fetcher = MarketDataFetcher()
