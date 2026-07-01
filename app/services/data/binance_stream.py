"""
Binance WebSocket price stream.

Opens a single combined stream for all active crypto assets and pushes
live mini-ticker updates to connected clients via socket.io.

Architecture:
  - One persistent wss:// thread started at app boot
  - On each price update: updates the in-process price cache + broadcasts
    via socket.io to subscribed clients
  - Auto-reconnects on drop with exponential backoff (max 60s)
  - Gracefully skips if websocket-client not installed
"""
from __future__ import annotations

import json
import logging
import threading
import time

logger = logging.getLogger(__name__)

# In-process live price cache: {symbol: {price, change_pct, volume, ts}}
_live_prices: dict[str, dict] = {}
_lock = threading.Lock()


def get_live_price(symbol: str) -> dict | None:
    with _lock:
        return _live_prices.get(symbol.upper())


def get_all_live_prices() -> dict:
    with _lock:
        return dict(_live_prices)


class BinanceStreamManager:
    """Manages a single combined WebSocket stream for all crypto symbols."""

    WS_BASE = "wss://stream.binance.com:9443/stream?streams="

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._app = None
        self._symbols: list[str] = []

    def start(self, app):
        """Start the stream in a background daemon thread."""
        self._app = app
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="binance-stream"
        )
        self._thread.start()
        logger.info("Binance WebSocket stream manager started")

    def stop(self):
        self._stop_event.set()

    def _get_symbols(self) -> list[str]:
        """Fetch active crypto symbols from DB."""
        try:
            with self._app.app_context():
                from app.models.asset import Asset
                assets = Asset.query.filter_by(
                    market="crypto", is_active=True, data_source="binance"
                ).all()
                return [a.symbol.upper() for a in assets]
        except Exception as e:
            logger.debug(f"BinanceStream: could not load symbols: {e}")
            return []

    def _run_loop(self):
        """Outer reconnect loop — retries with backoff on any failure."""
        backoff = 2
        while not self._stop_event.is_set():
            symbols = self._get_symbols()
            if not symbols:
                time.sleep(30)
                continue
            self._symbols = symbols
            try:
                self._connect(symbols)
                backoff = 2  # reset on clean disconnect
            except Exception as e:
                logger.debug(f"BinanceStream error: {e}")
            if not self._stop_event.is_set():
                logger.debug(f"BinanceStream reconnecting in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _connect(self, symbols: list[str]):
        """Open WS, read messages until error or stop signal."""
        try:
            import websocket  # websocket-client package
        except ImportError:
            logger.warning("websocket-client not installed — Binance stream disabled. "
                           "pip install websocket-client")
            self._stop_event.set()
            return

        # Build combined stream URL: <symbol>@miniTicker for each symbol
        streams = "/".join(f"{s.lower()}@miniTicker" for s in symbols)
        url = self.WS_BASE + streams

        ws = websocket.WebSocketApp(
            url,
            on_message=self._on_message,
            on_error=lambda ws, e: logger.debug(f"BinanceStream WS error: {e}"),
            on_close=lambda ws, c, m: logger.debug("BinanceStream WS closed"),
        )
        # run_forever blocks until connection drops
        ws.run_forever(ping_interval=20, ping_timeout=10)

    def _on_message(self, ws, raw: str):
        """Handle incoming miniTicker message."""
        try:
            msg = json.loads(raw)
            data = msg.get("data", msg)  # combined stream wraps in {"data": {...}}
            if data.get("e") != "24hrMiniTicker":
                return

            symbol   = data["s"]          # e.g. "BTCUSDT"
            price    = float(data["c"])   # last price
            open_    = float(data["o"])   # open 24h ago
            high     = float(data["h"])
            low      = float(data["l"])
            volume   = float(data["v"])
            chg_pct  = round((price - open_) / open_ * 100, 2) if open_ else 0.0

            tick = {
                "symbol":     symbol,
                "price":      price,
                "open":       open_,
                "high":       high,
                "low":        low,
                "volume":     volume,
                "change_pct": chg_pct,
                "change":     round(price - open_, 6),
                "ts":         int(data.get("E", time.time() * 1000)),
            }

            with _lock:
                _live_prices[symbol] = tick

            # Broadcast to subscribed socket.io clients
            self._broadcast(symbol, tick)

        except Exception as e:
            logger.debug(f"BinanceStream message parse error: {e}")

    def _broadcast(self, symbol: str, tick: dict):
        try:
            with self._app.app_context():
                from app.websocket.events import broadcast_ticker
                broadcast_ticker(symbol, tick)
        except Exception:
            pass
        # Real-time TP/SL check — close signals the moment price crosses a level
        try:
            from app.tasks.data_tasks import check_signals_for_price
            check_signals_for_price(symbol, tick["price"], self._app)
        except Exception:
            pass


binance_stream = BinanceStreamManager()
