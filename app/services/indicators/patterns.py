"""Candlestick pattern detection."""
import numpy as np
import pandas as pd


def detect_patterns(df: pd.DataFrame) -> list:
    """Detect candlestick patterns in the last few candles."""
    if len(df) < 5:
        return []

    patterns = []
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values

    def body(i): return abs(c[i] - o[i])
    def upper_shadow(i): return h[i] - max(o[i], c[i])
    def lower_shadow(i): return min(o[i], c[i]) - l[i]
    def candle_range(i): return h[i] - l[i]
    def is_bullish(i): return c[i] > o[i]
    def is_bearish(i): return c[i] < o[i]

    i = len(c) - 1

    # Doji
    if body(i) <= candle_range(i) * 0.1 and candle_range(i) > 0:
        patterns.append({"name": "Doji", "type": "neutral", "strength": 50})

    # Hammer
    if (lower_shadow(i) >= 2 * body(i) and upper_shadow(i) <= body(i) * 0.3
            and is_bullish(i) and body(i) > 0):
        patterns.append({"name": "Hammer", "type": "bullish", "strength": 70})

    # Shooting Star
    if (upper_shadow(i) >= 2 * body(i) and lower_shadow(i) <= body(i) * 0.3
            and is_bearish(i) and body(i) > 0):
        patterns.append({"name": "Shooting Star", "type": "bearish", "strength": 70})

    # Bullish Engulfing
    if (i >= 1 and is_bearish(i - 1) and is_bullish(i)
            and o[i] < c[i - 1] and c[i] > o[i - 1]):
        patterns.append({"name": "Bullish Engulfing", "type": "bullish", "strength": 80})

    # Bearish Engulfing
    if (i >= 1 and is_bullish(i - 1) and is_bearish(i)
            and o[i] > c[i - 1] and c[i] < o[i - 1]):
        patterns.append({"name": "Bearish Engulfing", "type": "bearish", "strength": 80})

    # Bullish Harami
    if (i >= 1 and is_bearish(i - 1) and is_bullish(i)
            and o[i] > c[i - 1] and c[i] < o[i - 1]):
        patterns.append({"name": "Bullish Harami", "type": "bullish", "strength": 60})

    # Bearish Harami
    if (i >= 1 and is_bullish(i - 1) and is_bearish(i)
            and o[i] < c[i - 1] and c[i] > o[i - 1]):
        patterns.append({"name": "Bearish Harami", "type": "bearish", "strength": 60})

    # Morning Star
    if (i >= 2 and is_bearish(i - 2) and body(i - 1) < body(i - 2) * 0.5
            and is_bullish(i) and c[i] > (o[i - 2] + c[i - 2]) / 2):
        patterns.append({"name": "Morning Star", "type": "bullish", "strength": 85})

    # Evening Star
    if (i >= 2 and is_bullish(i - 2) and body(i - 1) < body(i - 2) * 0.5
            and is_bearish(i) and c[i] < (o[i - 2] + c[i - 2]) / 2):
        patterns.append({"name": "Evening Star", "type": "bearish", "strength": 85})

    # Three White Soldiers
    if (i >= 2
            and all(is_bullish(j) for j in [i - 2, i - 1, i])
            and c[i] > c[i - 1] > c[i - 2]
            and o[i] > o[i - 1] > o[i - 2]):
        patterns.append({"name": "Three White Soldiers", "type": "bullish", "strength": 90})

    # Three Black Crows
    if (i >= 2
            and all(is_bearish(j) for j in [i - 2, i - 1, i])
            and c[i] < c[i - 1] < c[i - 2]
            and o[i] < o[i - 1] < o[i - 2]):
        patterns.append({"name": "Three Black Crows", "type": "bearish", "strength": 90})

    return patterns
