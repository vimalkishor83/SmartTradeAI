"""
News fetcher using Yahoo Finance RSS feeds — completely free, no API key needed.
"""
from __future__ import annotations
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

# Yahoo Finance symbol map (our symbol -> Yahoo symbol)
SYMBOL_MAP = {
    "NIFTY50":    "^NSEI",
    "BANKNIFTY":  "^NSEBANK",
    "SENSEX":     "^BSESN",
    "FINNIFTY":   "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "^NSMIDCP",
    "XAUUSD":     "GC=F",
    "XAGUSD":     "SI=F",
    "CLUSD":      "CL=F",
    "EURUSD":     "EURUSD=X",
    "GBPUSD":     "GBPUSD=X",
    "USDJPY":     "USDJPY=X",
    "AUDUSD":     "AUDUSD=X",
    "USDINR":     "INR=X",
    "BTCUSDT":    "BTC-USD",
    "ETHUSDT":    "ETH-USD",
    "BNBUSDT":    "BNB-USD",
    "SOLUSDT":    "SOL-USD",
    "XRPUSDT":    "XRP-USD",
}

# Reverse map: yahoo symbol -> our symbol
_REVERSE_MAP = {v: k for k, v in SYMBOL_MAP.items()}

BULLISH_WORDS = {"rise", "gain", "bull", "surge", "jump", "up", "high", "record", "rally", "growth", "profit", "beat"}
BEARISH_WORDS = {"fall", "drop", "bear", "crash", "plunge", "down", "low", "decline", "loss", "miss", "weak", "sell"}

RSS_BASE = "https://feeds.finance.yahoo.com/rss/2.0/headline"


def _score_sentiment(text: str) -> tuple[str, float]:
    """Return (sentiment_label, score) based on word counts in text."""
    words = text.lower().split()
    bullish = sum(1 for w in words if w in BULLISH_WORDS)
    bearish = sum(1 for w in words if w in BEARISH_WORDS)
    score = (bullish - bearish) / (bullish + bearish + 1)
    score = max(-1.0, min(1.0, score))
    if bullish > bearish:
        label = "positive"
    elif bearish > bullish:
        label = "negative"
    else:
        label = "neutral"
    return label, round(score, 4)


def _parse_rss(xml_text: str, related_symbols: list[str]) -> list[dict]:
    """Parse RSS XML and return list of news dicts."""
    items = []
    try:
        root = ET.fromstring(xml_text)
        ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
        channel = root.find("channel")
        if channel is None:
            return items
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            summary = (item.findtext("description") or "").strip()
            pub_date_str = item.findtext("pubDate") or ""
            published_at = None
            if pub_date_str:
                try:
                    published_at = parsedate_to_datetime(pub_date_str).replace(tzinfo=None)
                except Exception:
                    published_at = None
            sentiment, score = _score_sentiment(title + " " + summary)
            items.append({
                "title": title,
                "url": url,
                "summary": summary,
                "source": "Yahoo Finance",
                "sentiment": sentiment,
                "sentiment_score": score,
                "related_assets": related_symbols,
                "published_at": published_at,
            })
    except ET.ParseError as e:
        logger.warning(f"RSS XML parse error: {e}")
    return items


def fetch_news_for_symbols(symbols: list[str]) -> list[dict]:
    """
    Fetch Yahoo Finance RSS news for the given asset symbols.
    Also fetches general market news (S&P 500, Dow Jones).
    Returns a list of news item dicts.
    """
    all_items: list[dict] = []
    fetched_urls: set[str] = set()

    def _fetch_rss(yf_symbol: str, related: list[str]):
        url = f"{RSS_BASE}?s={yf_symbol}&region=US&lang=en-US"
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            for item in _parse_rss(resp.text, related):
                if item["url"] and item["url"] not in fetched_urls:
                    fetched_urls.add(item["url"])
                    all_items.append(item)
        except Exception as e:
            logger.debug(f"Yahoo RSS fetch failed for {yf_symbol}: {e}")

    # Fetch per-symbol feeds
    for sym in symbols:
        yf_sym = SYMBOL_MAP.get(sym, sym)
        _fetch_rss(yf_sym, [sym])

    # Fetch general market news
    _fetch_rss("^GSPC,^DJI", [])

    return all_items
