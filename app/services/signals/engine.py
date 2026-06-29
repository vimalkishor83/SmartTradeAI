"""
Core signal generation engine.
Analyzes OHLCV data and produces BUY/SELL/HOLD/EXIT signals with confidence scores.
"""
import logging
from datetime import datetime, timedelta
import pandas as pd

from app.services.indicators.calculator import calculate_all_indicators
from app.services.indicators.patterns import detect_patterns

logger = logging.getLogger(__name__)


class SignalEngine:

    TIMEFRAME_EXPIRY = {
        "1m": 5, "5m": 20, "15m": 60, "30m": 120,
        "1h": 240, "4h": 960, "1d": 2880,
    }

    def generate_signal(self, df: pd.DataFrame, asset, timeframe: str) -> dict | None:
        """Generate a trading signal for the given OHLCV data."""
        if df is None or len(df) < 60:
            return None

        try:
            indicators = calculate_all_indicators(df)
            patterns = detect_patterns(df)

            if not indicators:
                return None

            signal_type, reasoning, scores = self._evaluate_signal(indicators, patterns, df)
            confidence = sum(scores.values())

            entry_price = float(df["close"].iloc[-1])
            atr = indicators.get("atr") or entry_price * 0.01

            sl, t1, t2, t3 = self._calculate_levels(signal_type, entry_price, atr)
            rr = self._risk_reward(entry_price, sl, t1)

            expiry_minutes = self.TIMEFRAME_EXPIRY.get(timeframe, 60)
            label = self._confidence_label(confidence)

            return {
                "signal_type": signal_type,
                "entry_price": round(entry_price, 6),
                "stop_loss": round(sl, 6),
                "target1": round(t1, 6),
                "target2": round(t2, 6),
                "target3": round(t3, 6),
                "risk_reward": round(rr, 2),
                "confidence_score": round(confidence, 1),
                "confidence_label": label,
                "trend_score": scores.get("trend", 0),
                "momentum_score": scores.get("momentum", 0),
                "volume_score": scores.get("volume", 0),
                "pattern_score": scores.get("pattern", 0),
                "ai_score": scores.get("ai", 0),
                "indicators": indicators,
                "patterns": patterns,
                "reasoning": reasoning,
                "expires_at": datetime.utcnow() + timedelta(minutes=expiry_minutes),
            }
        except Exception as e:
            logger.error(f"Signal generation error for {asset}: {e}")
            return None

    def _evaluate_signal(self, ind: dict, patterns: list, df: pd.DataFrame):
        scores = {"trend": 0, "momentum": 0, "volume": 0, "pattern": 0, "ai": 0}
        bullish_points = 0
        bearish_points = 0
        reasons = []

        close = float(df["close"].iloc[-1])
        avg_volume = df["volume"].rolling(20).mean().iloc[-1] if "volume" in df.columns else 0
        curr_volume = df["volume"].iloc[-1] if "volume" in df.columns else 0

        # --- TREND (30 pts) ---
        ema20 = ind.get("ema20") or 0
        ema50 = ind.get("ema50") or 0
        vwap = ind.get("vwap") or 0
        supertrend_dir = ind.get("supertrend_direction", "up")

        if ema20 and ema50:
            if ema20 > ema50:
                bullish_points += 8
                reasons.append("EMA20 above EMA50 (bullish trend)")
            else:
                bearish_points += 8
                reasons.append("EMA20 below EMA50 (bearish trend)")

        if vwap and close > vwap:
            bullish_points += 7
            reasons.append("Price above VWAP")
        elif vwap:
            bearish_points += 7

        if supertrend_dir == "up":
            bullish_points += 8
            reasons.append("SuperTrend bullish")
        else:
            bearish_points += 8
            reasons.append("SuperTrend bearish")

        # Ichimoku
        ichi_a = ind.get("ichimoku_senkou_a") or 0
        ichi_b = ind.get("ichimoku_senkou_b") or 0
        if ichi_a and ichi_b and close > max(ichi_a, ichi_b):
            bullish_points += 7
        elif ichi_a and ichi_b:
            bearish_points += 7

        scores["trend"] = min(30, int((bullish_points / max(bullish_points + bearish_points, 1)) * 30))

        # --- MOMENTUM (20 pts) ---
        rsi = ind.get("rsi") or 50
        macd = ind.get("macd") or 0
        macd_signal = ind.get("macd_signal") or 0
        macd_hist = ind.get("macd_hist") or 0

        if 50 <= rsi <= 70:
            bullish_points += 5
            reasons.append(f"RSI bullish zone ({rsi:.1f})")
        elif rsi < 30:
            bullish_points += 8
            reasons.append(f"RSI oversold ({rsi:.1f}) - reversal possible")
        elif 30 <= rsi < 50:
            bearish_points += 5
        elif rsi > 70:
            bearish_points += 3
        elif rsi < 40:
            bearish_points += 8

        if macd > macd_signal and macd_hist > 0:
            bullish_points += 7
            reasons.append("MACD bullish crossover")
        elif macd < macd_signal and macd_hist < 0:
            bearish_points += 7
            reasons.append("MACD bearish crossover")

        scores["momentum"] = min(20, int(abs(bullish_points - bearish_points) / 2))

        # --- VOLUME (15 pts) ---
        if avg_volume and curr_volume > avg_volume * 1.5:
            scores["volume"] = 15
            reasons.append("Volume spike confirming move")
        elif avg_volume and curr_volume > avg_volume:
            scores["volume"] = 8

        # --- PATTERN (15 pts) ---
        bull_patterns = [p for p in patterns if p["type"] == "bullish"]
        bear_patterns = [p for p in patterns if p["type"] == "bearish"]

        if bull_patterns:
            scores["pattern"] = min(15, int(max(p["strength"] for p in bull_patterns) / 7))
            reasons.append(f"Pattern: {bull_patterns[0]['name']}")
        elif bear_patterns:
            scores["pattern"] = min(15, int(max(p["strength"] for p in bear_patterns) / 7))
            reasons.append(f"Pattern: {bear_patterns[0]['name']}")

        # --- AI placeholder (20 pts) ---
        scores["ai"] = 10  # Will be filled by AI module

        # Determine signal direction
        total = bullish_points + bearish_points
        if total == 0:
            signal_type = "HOLD"
        elif bullish_points / total >= 0.65:
            signal_type = "BUY"
        elif bearish_points / total >= 0.65:
            signal_type = "SELL"
        else:
            signal_type = "HOLD"

        return signal_type, " | ".join(reasons), scores

    def _calculate_levels(self, signal_type: str, price: float, atr: float):
        if signal_type == "BUY":
            sl = price - 1.5 * atr
            t1 = price + 1.5 * atr
            t2 = price + 2.5 * atr
            t3 = price + 4.0 * atr
        elif signal_type == "SELL":
            sl = price + 1.5 * atr
            t1 = price - 1.5 * atr
            t2 = price - 2.5 * atr
            t3 = price - 4.0 * atr
        else:
            sl = price - atr
            t1 = price + atr
            t2 = price + 1.5 * atr
            t3 = price + 2.5 * atr
        return sl, t1, t2, t3

    def _risk_reward(self, entry, sl, target):
        risk = abs(entry - sl)
        reward = abs(target - entry)
        return round(reward / risk, 2) if risk > 0 else 0

    def _confidence_label(self, score):
        if score >= 90:
            return "Very Strong"
        elif score >= 75:
            return "Strong"
        elif score >= 60:
            return "Moderate"
        return "Weak"


signal_engine = SignalEngine()
