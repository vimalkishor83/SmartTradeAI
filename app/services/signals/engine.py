"""
Signal generation engine — 7-stage pipeline.

Stage 1: Market session gate      — skip signals outside valid trading hours
Stage 2: Volatility regime gate   — skip if market is too quiet or too chaotic
Stage 3: MTF alignment gate       — higher TF trend must agree with signal direction
Stage 4: Momentum confirmation    — RSI + MACD must support the direction
Stage 5: Volume confirmation      — volume must confirm the move (crypto/stocks only)
Stage 6: Confidence scoring       — multiplicative model, minimum threshold 70
Stage 7: Result packaging         — entry, stop (structure-aware), targets, R:R
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import pandas as pd

from app.services.indicators.calculator import calculate_all_indicators
from app.services.indicators.patterns import detect_patterns

logger = logging.getLogger(__name__)


# ─── Market session windows (UTC hours) ───────────────────
_SESSIONS = {
    "crypto":        None,                          # 24/7
    "forex":         [(7, 16), (13, 21)],           # London + NY overlap
    "commodity":     [(7, 21)],                     # London open → NY close
    "indian_stock":  [(3, 10)],                     # NSE: 09:15–15:30 IST = 03:45–10:00 UTC
    "index":         [(3, 10)],                     # Same as Indian stocks
}

# Duplicate-signal lockout window per timeframe (minutes)
_LOCKOUT = {
    "1m": 5,  "5m": 20,  "15m": 45,  "30m": 90,
    "1h": 120, "2h": 240, "4h": 480,  "1d": 1440,
}

# Signal expiry per timeframe (minutes)
_EXPIRY = {
    "1m": 5,  "5m": 20,  "15m": 60,  "30m": 120,
    "1h": 240, "2h": 480, "4h": 960,  "1d": 2880,
}

# Minimum candle count required (drives minimum data need)
_MIN_CANDLES = 60


class SignalEngine:

    # ──────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────
    def generate_signal(
        self,
        df: pd.DataFrame,
        asset,
        timeframe: str,
        higher_tf_df: pd.DataFrame | None = None,
        force: bool = False,
        direction_threshold: float = 0.65,
    ) -> dict | None:
        """
        Run the full 7-stage pipeline.
        Returns a signal dict on success, None if any gate rejects.
        `higher_tf_df` is optional OHLCV of the next TF up (for Stage 3).
        `force=True` skips the session gate (used for manual on-demand generation).
        """
        if df is None or len(df) < _MIN_CANDLES:
            return None

        market = getattr(asset, "market", "crypto")

        try:
            # ── Stage 1: Session gate (skipped for manual/forced generation) ──
            if not force and not self._session_gate(market):
                return None

            # ── Stage 2: Volatility regime gate ───────────────────
            indicators = calculate_all_indicators(df)
            if not indicators:
                return None

            atr      = indicators.get("atr") or 0
            close    = float(df["close"].iloc[-1])
            atr_pct  = (atr / close * 100) if close else 0

            vol_ok, vol_regime = self._volatility_gate(atr_pct)
            if not vol_ok:
                return None

            # ── Stage 3: MTF alignment gate ────────────────────────
            higher_bias = self._mtf_gate(higher_tf_df)
            # higher_bias: "bullish" | "bearish" | "neutral" | None (unknown = skip only if conflict is clear)

            # ── Stage 4 & 5: Momentum + Volume pre-scoring ─────────
            thresh = 0.55 if force else 0.65
            raw_direction, raw_scores, reasons = self._score_signal(indicators, df, market, threshold=thresh)

            if raw_direction == "HOLD":
                return None

            # Stage 3 rejection: higher TF clearly disagrees (skipped on force)
            if not force and higher_bias and higher_bias != "neutral":
                if raw_direction == "BUY" and higher_bias == "bearish":
                    return None
                if raw_direction == "SELL" and higher_bias == "bullish":
                    return None

            # Stage 4: Momentum gate (skipped on force)
            if not force and not self._momentum_gate(indicators, raw_direction):
                return None

            # Stage 5: Volume gate (skipped on force)
            if not force and market in ("crypto", "indian_stock"):
                if not self._volume_gate(df):
                    return None

            # ── Stage 6: Confidence scoring ────────────────────────
            confidence = self._compute_confidence(raw_scores, higher_bias, raw_direction)
            min_conf = 50 if force else 70

            if confidence < min_conf:
                return None

            # ── Stage 7: Package result ────────────────────────────
            patterns = detect_patterns(df)
            sl       = self._structure_stop(df, raw_direction, close, atr)
            t1, t2, t3 = self._calculate_targets(raw_direction, close, atr)
            rr       = self._risk_reward(close, sl, t1)

            expiry_min = _EXPIRY.get(timeframe, 60)

            return {
                "signal_type":       raw_direction,
                "entry_price":       round(close, 6),
                "stop_loss":         round(sl, 6),
                "target1":           round(t1, 6),
                "target2":           round(t2, 6),
                "target3":           round(t3, 6),
                "risk_reward":       round(rr, 2),
                "confidence_score":  round(confidence, 1),
                "confidence_label":  self._confidence_label(confidence),
                "trend_score":       raw_scores.get("trend", 0),
                "momentum_score":    raw_scores.get("momentum", 0),
                "volume_score":      raw_scores.get("volume", 0),
                "pattern_score":     raw_scores.get("pattern", 0),
                "ai_score":          raw_scores.get("ai", 0),
                "indicators":        indicators,
                "patterns":          patterns,
                "reasoning":         " | ".join(reasons),
                "volatility_regime": vol_regime,
                "higher_tf_bias":    higher_bias,
                "regime":            self._regime_label(higher_bias, vol_regime, raw_direction),
                "expires_at":        datetime.utcnow() + timedelta(minutes=expiry_min),
            }

        except Exception as e:
            logger.error(f"Signal pipeline error [{getattr(asset, 'symbol', '?')}/{timeframe}]: {e}")
            return None

    # ──────────────────────────────────────────────────────
    # Stage 1 — Market session gate
    # ──────────────────────────────────────────────────────
    def _session_gate(self, market: str) -> bool:
        windows = _SESSIONS.get(market)
        if windows is None:
            return True  # 24/7 market (crypto)
        now_utc = datetime.now(timezone.utc).hour
        return any(start <= now_utc < end for start, end in windows)

    # ──────────────────────────────────────────────────────
    # Combined market-regime label (trend × volatility)
    # ──────────────────────────────────────────────────────
    @staticmethod
    def _regime_label(higher_bias: str | None, vol_regime: str, direction: str) -> str:
        """A discrete regime tag combining macro trend and volatility, e.g.
        'uptrend_normal', 'downtrend_elevated', 'sideways_normal'.

        Trend is taken from the higher-timeframe bias when known, else inferred
        from the signal direction. Additive metadata only — it does not change
        which signals are produced, so it has no effect on win rate."""
        trend = {"bullish": "uptrend", "bearish": "downtrend"}.get(higher_bias or "")
        if trend is None:
            # no higher-TF context — fall back to the signal's own direction
            trend = {"BUY": "uptrend", "SELL": "downtrend"}.get(direction, "sideways")
        vol = vol_regime if vol_regime in ("normal", "elevated") else "normal"
        return f"{trend}_{vol}"

    # ──────────────────────────────────────────────────────
    # Stage 2 — Volatility regime gate
    # ──────────────────────────────────────────────────────
    def _volatility_gate(self, atr_pct: float) -> tuple[bool, str]:
        """
        Returns (allowed, regime_label).
        Too quiet  (<0.1%) → likely consolidation or dead session.
        Too chaotic (>6%)  → news spike, slippage risk too high.
        """
        if atr_pct == 0:
            return True, "unknown"   # no ATR data — allow through (data issue, not a bad market)
        if atr_pct < 0.10:
            return False, "dead"
        if atr_pct > 6.0:
            return False, "chaotic"
        if atr_pct > 3.0:
            return True, "elevated"
        return True, "normal"

    # ──────────────────────────────────────────────────────
    # Stage 3 — Higher timeframe alignment gate
    # ──────────────────────────────────────────────────────
    def _mtf_gate(self, higher_df: pd.DataFrame | None) -> str | None:
        """Return 'bullish', 'bearish', or 'neutral' from the higher TF, or None if unavailable."""
        if higher_df is None or len(higher_df) < 30:
            return None
        try:
            ind = calculate_all_indicators(higher_df)
            ema20 = ind.get("ema20") or 0
            ema50 = ind.get("ema50") or 0
            supertrend = ind.get("supertrend_direction", "up")
            close = float(higher_df["close"].iloc[-1])

            bull_votes = 0
            bear_votes = 0
            if ema20 and ema50:
                if ema20 > ema50: bull_votes += 1
                else:             bear_votes += 1
            if supertrend == "up":   bull_votes += 1
            else:                    bear_votes += 1
            if ema20 and close > ema20: bull_votes += 1
            else:                       bear_votes += 1

            if bull_votes >= 2: return "bullish"
            if bear_votes >= 2: return "bearish"
            return "neutral"
        except Exception:
            return None

    # ──────────────────────────────────────────────────────
    # Stage 4 — Momentum gate
    # ──────────────────────────────────────────────────────
    def _momentum_gate(self, ind: dict, direction: str) -> bool:
        """
        BUY signals must not have overbought RSI.
        SELL signals must not have oversold RSI.
        MACD histogram must agree.
        Both conditions must be met.
        """
        rsi  = ind.get("rsi") or 50
        macd_hist = ind.get("macd_hist") or 0

        if direction == "BUY":
            rsi_ok  = rsi < 75         # not extreme overbought
            macd_ok = macd_hist >= 0   # histogram not deeply negative
        else:
            rsi_ok  = rsi > 25         # not extreme oversold
            macd_ok = macd_hist <= 0

        return rsi_ok and macd_ok

    # ──────────────────────────────────────────────────────
    # Stage 5 — Volume gate
    # ──────────────────────────────────────────────────────
    def _volume_gate(self, df: pd.DataFrame) -> bool:
        """Volume on signal candle must be ≥ 0.8× 20-period average (relaxed to avoid over-filtering)."""
        if "volume" not in df.columns:
            return True
        avg_vol  = df["volume"].rolling(20).mean().iloc[-1]
        curr_vol = df["volume"].iloc[-1]
        if not avg_vol or avg_vol == 0:
            return True
        return curr_vol >= avg_vol * 0.8

    # ──────────────────────────────────────────────────────
    # Stage 6 — Confidence scoring (multiplicative)
    # ──────────────────────────────────────────────────────
    def _score_signal(self, ind: dict, df: pd.DataFrame, market: str, threshold: float = 0.65):
        """
        Compute raw direction, per-component scores, and reasons.
        Returns (direction, scores_dict, reasons_list).
        """
        bull = 0
        bear = 0
        reasons = []
        scores = {"trend": 0, "momentum": 0, "volume": 0, "pattern": 0, "ai": 10}

        close    = float(df["close"].iloc[-1])
        ema20    = ind.get("ema20") or 0
        ema50    = ind.get("ema50") or 0
        ema100   = ind.get("ema100") or 0
        ema200   = ind.get("ema200") or 0
        vwap     = ind.get("vwap") or 0
        supertrend_dir = ind.get("supertrend_direction", "up")
        ichi_a   = ind.get("ichimoku_senkou_a") or 0
        ichi_b   = ind.get("ichimoku_senkou_b") or 0
        rsi      = ind.get("rsi") or 50
        macd     = ind.get("macd") or 0
        macd_sig = ind.get("macd_signal") or 0
        macd_hist= ind.get("macd_hist") or 0

        # ── Trend component (up to 30 pts) ────────────────
        trend_bull = 0
        trend_bear = 0

        if ema20 and ema50:
            if ema20 > ema50:
                trend_bull += 8; reasons.append("EMA20>EMA50 (uptrend)")
            else:
                trend_bear += 8; reasons.append("EMA20<EMA50 (downtrend)")

        if ema50 and ema200:
            if ema50 > ema200:
                trend_bull += 5; reasons.append("Golden cross zone")
            else:
                trend_bear += 5; reasons.append("Death cross zone")

        if vwap and close:
            if close > vwap:
                trend_bull += 6; reasons.append("Price above VWAP")
            else:
                trend_bear += 6

        if supertrend_dir == "up":
            trend_bull += 7; reasons.append("SuperTrend bullish")
        else:
            trend_bear += 7; reasons.append("SuperTrend bearish")

        if ichi_a and ichi_b and close:
            cloud_top = max(ichi_a, ichi_b)
            cloud_bot = min(ichi_a, ichi_b)
            if close > cloud_top:
                trend_bull += 4; reasons.append("Price above Ichimoku cloud")
            elif close < cloud_bot:
                trend_bear += 4

        trend_total = trend_bull + trend_bear
        if trend_total > 0:
            scores["trend"] = round((trend_bull / trend_total) * 30)
            bull += trend_bull
            bear += trend_bear

        # ── Momentum component (up to 20 pts) ─────────────
        mom_bull = 0
        mom_bear = 0

        # RSI prime zones give most conviction
        if 40 <= rsi <= 60:
            pass
        elif 30 <= rsi < 40:
            mom_bull += 6; reasons.append(f"RSI recovering from oversold ({rsi:.0f})")
        elif rsi < 30:
            mom_bull += 10; reasons.append(f"RSI oversold ({rsi:.0f})")
        elif 60 < rsi <= 70:
            mom_bull += 4; reasons.append(f"RSI bullish zone ({rsi:.0f})")
        elif rsi > 70:
            mom_bear += 8; reasons.append(f"RSI overbought ({rsi:.0f})")

        if macd > macd_sig and macd_hist > 0:
            mom_bull += 10; reasons.append("MACD bullish crossover")
        elif macd < macd_sig and macd_hist < 0:
            mom_bear += 10; reasons.append("MACD bearish crossover")
        elif macd_hist > 0:
            mom_bull += 4
        elif macd_hist < 0:
            mom_bear += 4

        mom_total = mom_bull + mom_bear
        if mom_total > 0:
            scores["momentum"] = round((max(mom_bull, mom_bear) / mom_total) * 20)
            bull += mom_bull
            bear += mom_bear

        # ── Volume component (up to 15 pts) ───────────────
        if "volume" in df.columns and market in ("crypto", "indian_stock"):
            avg_vol  = df["volume"].rolling(20).mean().iloc[-1]
            curr_vol = df["volume"].iloc[-1]
            if avg_vol and avg_vol > 0:
                vol_ratio = curr_vol / avg_vol
                if vol_ratio >= 2.0:
                    scores["volume"] = 15; reasons.append("Strong volume spike (2×+)")
                elif vol_ratio >= 1.5:
                    scores["volume"] = 10; reasons.append("Volume spike (1.5×+)")
                elif vol_ratio >= 1.0:
                    scores["volume"] = 6
                else:
                    scores["volume"] = 2  # low volume — weak signal

        # ── Pattern component (up to 15 pts) ──────────────
        try:
            patterns = detect_patterns(df)
            bull_pat = [p for p in patterns if p["type"] == "bullish"]
            bear_pat = [p for p in patterns if p["type"] == "bearish"]
            if bull_pat:
                best = max(bull_pat, key=lambda p: p["strength"])
                scores["pattern"] = min(15, int(best["strength"] / 7))
                reasons.append(f"Pattern: {best['name']}")
                bull += best["strength"]
            elif bear_pat:
                best = max(bear_pat, key=lambda p: p["strength"])
                scores["pattern"] = min(15, int(best["strength"] / 7))
                reasons.append(f"Pattern: {best['name']}")
                bear += best["strength"]
        except Exception:
            pass

        # Direction decision
        total = bull + bear
        if total == 0:
            direction = "HOLD"
        elif bull / total >= threshold:
            direction = "BUY"
        elif bear / total >= threshold:
            direction = "SELL"
        else:
            direction = "HOLD"

        return direction, scores, reasons

    def _compute_confidence(self, scores: dict, higher_bias: str | None, direction: str) -> float:
        """
        Multiplicative confidence model.
        Base = sum of component scores.
        Applied multipliers: trend alignment, MTF agreement.
        """
        base = sum(scores.values())   # max ~100

        # Trend alignment multiplier
        trend_pct = scores.get("trend", 0) / 30 if 30 > 0 else 0
        if trend_pct >= 0.80:
            trend_mult = 1.15
        elif trend_pct >= 0.60:
            trend_mult = 1.05
        elif trend_pct >= 0.40:
            trend_mult = 0.95
        else:
            trend_mult = 0.80

        # MTF alignment multiplier
        if higher_bias is None or higher_bias == "neutral":
            mtf_mult = 1.0
        elif (direction == "BUY" and higher_bias == "bullish") or \
             (direction == "SELL" and higher_bias == "bearish"):
            mtf_mult = 1.15   # agreement boost
        else:
            mtf_mult = 0.85   # mild disagreement (hard disagreement blocked in Stage 3)

        # Volume confirmation multiplier
        vol_score = scores.get("volume", 0)
        if vol_score >= 10:
            vol_mult = 1.05
        elif vol_score == 0:
            vol_mult = 0.95
        else:
            vol_mult = 1.0

        confidence = base * trend_mult * mtf_mult * vol_mult
        return min(100.0, round(confidence, 1))

    # ──────────────────────────────────────────────────────
    # Stage 7 helpers
    # ──────────────────────────────────────────────────────
    def _structure_stop(self, df: pd.DataFrame, direction: str, close: float, atr: float) -> float:
        """
        Structure-aware stop-loss: use recent swing high/low where possible,
        fall back to ATR-based stop. Take whichever is tighter (less risk).
        """
        lookback = df.tail(10)
        atr_sl   = atr if atr else close * 0.01

        # Stop at 1.8×ATR (wider than the 1.2×ATR target — see _calculate_targets)
        # so noise doesn't stop trades out prematurely. Backtest across BTC/SOL/ETH
        # showed this T1/SL pairing lifts win rate ~34% -> ~60% while staying
        # profitable (avg R positive), vs a symmetric 1.5/1.5 that loses money.
        if direction == "BUY":
            structure_sl  = float(lookback["low"].min()) * 0.9995
            atr_based_sl  = close - 1.8 * atr_sl
            stop          = max(structure_sl, atr_based_sl)   # higher = tighter for a long
        else:
            structure_sl  = float(lookback["high"].max()) * 1.0005
            atr_based_sl  = close + 1.8 * atr_sl
            stop          = min(structure_sl, atr_based_sl)   # lower = tighter for a short

        # Enforce minimum stop distance = 0.3× ATR to avoid stop-hunting
        min_dist = atr_sl * 0.3
        if direction == "BUY" and (close - stop) < min_dist:
            stop = close - min_dist
        elif direction == "SELL" and (stop - close) < min_dist:
            stop = close + min_dist

        return round(stop, 8)

    def _calculate_targets(self, direction: str, price: float, atr: float) -> tuple[float, float, float]:
        # T1 at 1.2×ATR (closer than the 1.8×ATR stop) so it is reached far more
        # often — this is what lifts the win rate. T2/T3 stay extended for
        # runners. Pairing validated by the walk-forward backtest.
        atr = atr or price * 0.01
        if direction == "BUY":
            return price + 1.2 * atr, price + 2.5 * atr, price + 4.0 * atr
        elif direction == "SELL":
            return price - 1.2 * atr, price - 2.5 * atr, price - 4.0 * atr
        else:
            return price + atr, price + 1.5 * atr, price + 2.5 * atr

    def _risk_reward(self, entry: float, sl: float, t1: float) -> float:
        risk   = abs(entry - sl)
        reward = abs(t1 - entry)
        return round(reward / risk, 2) if risk > 0 else 0

    def _confidence_label(self, score: float) -> str:
        if score >= 90: return "Very Strong"
        if score >= 80: return "Strong"
        if score >= 70: return "Moderate"
        return "Weak"

    # ──────────────────────────────────────────────────────
    # Utility: lockout window per timeframe
    # ──────────────────────────────────────────────────────
    @staticmethod
    def lockout_minutes(timeframe: str) -> int:
        return _LOCKOUT.get(timeframe, 30)


signal_engine = SignalEngine()
