"""
Delta Exchange India WebSocket price stream.

Opens a single connection subscribed to the v2/ticker channel for all
active crypto assets and pushes live ticker updates to connected clients
via socket.io.

Architecture (mirrors binance_stream.py):
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

from app.services.data.fetcher import to_delta_symbol, from_delta_symbol

logger = logging.getLogger(__name__)

# In-process live price cache: {symbol: {price, change_pct, volume, ts}}
# Keyed by OUR symbol (e.g. "BTCUSDT"), not Delta's native symbol.
_live_prices: dict[str, dict] = {}
_lock = threading.Lock()


def get_live_price(symbol: str) -> dict | None:
    with _lock:
        return _live_prices.get(symbol.upper())


def get_all_live_prices() -> dict:
    with _lock:
        return dict(_live_prices)


class DeltaStreamManager:
    """Manages a single WebSocket connection subscribed to Delta's v2/ticker channel."""

    WS_URL = "wss://socket.india.delta.exchange"

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._app = None
        self._symbols: list[str] = []   # our symbols, e.g. ["BTCUSDT", ...]

    def start(self, app):
        """Start the stream in a background daemon thread."""
        self._app = app
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="delta-stream"
        )
        self._thread.start()
        logger.info("Delta Exchange WebSocket stream manager started")

    def stop(self):
        self._stop_event.set()

    def _get_symbols(self) -> list[str]:
        """Fetch active crypto symbols from DB that have a valid Delta mapping."""
        try:
            with self._app.app_context():
                from app.models.asset import Asset
                assets = Asset.query.filter_by(market="crypto", is_active=True).all()
                return [a.symbol.upper() for a in assets if to_delta_symbol(a.symbol)]
        except Exception as e:
            logger.debug(f"DeltaStream: could not load symbols: {e}")
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
                logger.debug(f"DeltaStream error: {e}")
            if not self._stop_event.is_set():
                logger.debug(f"DeltaStream reconnecting in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def _connect(self, symbols: list[str]):
        """Open WS, subscribe to v2/ticker for our symbols, read until error/stop."""
        try:
            import websocket  # websocket-client package
        except ImportError:
            logger.warning("websocket-client not installed — Delta stream disabled. "
                           "pip install websocket-client")
            self._stop_event.set()
            return

        delta_symbols = [to_delta_symbol(s) for s in symbols]

        def on_open(ws):
            sub = {
                "type": "subscribe",
                "payload": {"channels": [{"name": "v2/ticker", "symbols": delta_symbols}]},
            }
            ws.send(json.dumps(sub))

        ws = websocket.WebSocketApp(
            self.WS_URL,
            on_open=on_open,
            on_message=self._on_message,
            on_error=lambda ws, e: logger.debug(f"DeltaStream WS error: {e}"),
            on_close=lambda ws, c, m: logger.debug("DeltaStream WS closed"),
        )
        # run_forever blocks until connection drops
        ws.run_forever(ping_interval=20, ping_timeout=10)

    def _on_message(self, ws, raw: str):
        """Handle incoming v2/ticker message."""
        try:
            msg = json.loads(raw)
            if msg.get("type") != "v2/ticker":
                return

            delta_symbol = msg.get("symbol")
            if not delta_symbol:
                return
            our_symbol = from_delta_symbol(delta_symbol)

            close  = float(msg.get("close", 0) or 0)
            open_  = float(msg.get("open", 0) or 0)
            high   = float(msg.get("high", 0) or 0)
            low    = float(msg.get("low", 0) or 0)
            volume = float(msg.get("volume", 0) or 0)
            chg_pct = round((close - open_) / open_ * 100, 2) if open_ else 0.0

            tick = {
                "symbol":     our_symbol,
                "price":      close,
                "open":       open_,
                "high":       high,
                "low":        low,
                "volume":     volume,
                "change_pct": chg_pct,
                "change":     round(close - open_, 6),
                "ts":         int(msg.get("timestamp", time.time() * 1_000_000) / 1000),
                # Server-side wall-clock receive time — used by
                # MarketDataFetcher.fetch_ticker to decide whether this cached
                # WS price is fresh enough to serve instead of a REST call.
                "_recv_ts":   time.time(),
            }

            with _lock:
                _live_prices[our_symbol] = tick

            # Broadcast to subscribed socket.io clients
            self._broadcast(our_symbol, tick)

        except Exception as e:
            logger.debug(f"DeltaStream message parse error: {e}")

    def _broadcast(self, symbol: str, tick: dict):
        try:
            with self._app.app_context():
                from app.websocket.events import broadcast_ticker
                broadcast_ticker(symbol, tick)
        except Exception as e:
            logger.debug(f"DeltaStream ticker broadcast failed [{symbol}]: {e}")
        # Real-time TP/SL check — close signals the moment price crosses a level.
        # A failure here means a signal may not close on time, so it is logged
        # (debug, to avoid per-tick spam) rather than silently swallowed.
        try:
            from app.tasks.data_tasks import check_signals_for_price
            check_signals_for_price(symbol, tick["price"], self._app)
        except Exception as e:
            logger.debug(f"DeltaStream real-time TP/SL check failed [{symbol}]: {e}")


delta_stream = DeltaStreamManager()
