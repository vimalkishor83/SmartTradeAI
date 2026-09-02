"""Unit test: proves market_board()'s live-preview fallback (used by the
Terminal page for an asset+timeframe with no persisted Signal) freezes its
entry/stop-loss/targets instead of recomputing them from the current price
on every call — the actual bug reported: "entry, stop loss, tp1/2/3 should
not change until TP or SL hit," which used to fail because analyze() derives
all of those from whatever the close price happens to be at call time.

current_price itself is deliberately read from fetch_ticker() (a continuously
live quote), not the OHLCV candle's own close — the candle only moves when a
candle actually closes, which made "current price" look frozen too between
candle closes once entry/stop/targets stopped moving in lockstep with it.
"""
import pandas as pd
from unittest.mock import patch


class FakeAsset:
    symbol = "TESTUSD"
    market = "crypto"

    def __init__(self, asset_id):
        self.id = asset_id


def _df(close):
    return pd.DataFrame({"close": [close] * 5})


def _ticker(price):
    return patch("app.api.v1.signals.market_fetcher.fetch_ticker", return_value={"price": price})


class TestFrozenLiveRead:
    def test_second_call_keeps_frozen_levels_but_updates_current_price(self, app):
        from app.api.v1.signals import _frozen_live_read

        buy_result = {
            "available": True, "signal_type": "BUY", "confidence_score": 72.0,
            "entry_price": 100.0, "stop_loss": 95.0,
            "target1": 105.0, "target2": 110.0, "target3": 115.0,
            "risk_reward": 2.0,
        }
        asset = FakeAsset(1001)
        with app.app_context():
            with patch("app.api.v1.signals.signal_engine.analyze", return_value=dict(buy_result)), \
                 _ticker(100.0):
                first = _frozen_live_read(asset, "1h", _df(100.0))
            assert first["entry_price"] == 100.0
            assert first["current_price"] == 100.0

            # A live tick moved the price, but nowhere near the frozen
            # stop-loss (95) or final target (115) — analyze() must NOT
            # be called again; entry/stop/targets stay exactly as first
            # computed even though the OHLCV candle's own close (still
            # 100.0 here — candles don't reprint every tick) hasn't moved.
            with patch("app.api.v1.signals.signal_engine.analyze") as mock_analyze, \
                 _ticker(102.5):
                second = _frozen_live_read(asset, "1h", _df(100.0))
            mock_analyze.assert_not_called()
            assert second["entry_price"] == 100.0
            assert second["stop_loss"] == 95.0
            assert second["target1"] == 105.0
            assert second["target3"] == 115.0
            # ...but current_price DID move, per the report ("current
            # price should [be] live") — driven by the live ticker quote,
            # not the unchanged OHLCV candle close.
            assert second["current_price"] == 102.5

    def test_price_reaching_final_target_recomputes_a_fresh_read(self, app):
        from app.api.v1.signals import _frozen_live_read

        buy_result = {
            "available": True, "signal_type": "BUY", "confidence_score": 72.0,
            "entry_price": 100.0, "stop_loss": 95.0,
            "target1": 105.0, "target2": 110.0, "target3": 115.0,
            "risk_reward": 2.0,
        }
        asset = FakeAsset(1002)
        with app.app_context():
            with patch("app.api.v1.signals.signal_engine.analyze", return_value=dict(buy_result)), \
                 _ticker(100.0):
                _frozen_live_read(asset, "1h", _df(100.0))

            # The live ticker ran through the final target — the
            # hypothetical trade has resolved, so this should compute
            # (and freeze) a new read instead of continuing to serve the
            # old, now-irrelevant one.
            new_result = {
                "available": True, "signal_type": "BUY", "confidence_score": 68.0,
                "entry_price": 116.0, "stop_loss": 112.0,
                "target1": 120.0, "target2": 124.0, "target3": 128.0,
                "risk_reward": 1.5,
            }
            with patch("app.api.v1.signals.signal_engine.analyze", return_value=dict(new_result)) as mock_analyze, \
                 _ticker(116.0):
                resolved = _frozen_live_read(asset, "1h", _df(116.0))
            mock_analyze.assert_called_once()
            assert resolved["entry_price"] == 116.0
            assert resolved["stop_loss"] == 112.0

    def test_price_hitting_stop_loss_also_recomputes(self, app):
        from app.api.v1.signals import _frozen_live_read

        sell_result = {
            "available": True, "signal_type": "SELL", "confidence_score": 70.0,
            "entry_price": 100.0, "stop_loss": 105.0,
            "target1": 95.0, "target2": 90.0, "target3": 85.0,
            "risk_reward": 1.8,
        }
        asset = FakeAsset(1003)
        with app.app_context():
            with patch("app.api.v1.signals.signal_engine.analyze", return_value=dict(sell_result)), \
                 _ticker(100.0):
                _frozen_live_read(asset, "1h", _df(100.0))

            # The live ticker rose past the SELL's stop-loss (105) — resolved.
            with patch("app.api.v1.signals.signal_engine.analyze", return_value=dict(sell_result)) as mock_analyze, \
                 _ticker(106.0):
                _frozen_live_read(asset, "1h", _df(100.0))
            mock_analyze.assert_called_once()

    def test_ticker_unavailable_falls_back_to_ohlcv_close(self, app):
        """fetch_ticker() failing (returns None, or raises) shouldn't ever
        break the card — current_price should just fall back to the
        OHLCV close rather than the whole read blowing up."""
        from app.api.v1.signals import _frozen_live_read

        buy_result = {
            "available": True, "signal_type": "BUY", "confidence_score": 72.0,
            "entry_price": 100.0, "stop_loss": 95.0,
            "target1": 105.0, "target2": 110.0, "target3": 115.0,
            "risk_reward": 2.0,
        }
        asset = FakeAsset(1004)
        with app.app_context():
            with patch("app.api.v1.signals.signal_engine.analyze", return_value=dict(buy_result)), \
                 patch("app.api.v1.signals.market_fetcher.fetch_ticker", return_value=None):
                result = _frozen_live_read(asset, "1h", _df(100.0))
            assert result["current_price"] == 100.0
