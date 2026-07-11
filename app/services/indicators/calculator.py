"""
Technical indicators calculator using pandas-ta and numpy.
All methods accept a DataFrame with columns: open, high, low, close, volume
"""
import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(series: pd.Series, period=20, std_dev=2):
    sma = calculate_sma(series, period)
    std = series.rolling(window=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    width = (upper - lower) / sma * 100
    return upper, sma, lower, width


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.DataFrame({
        "hl": high - low,
        "hpc": (high - prev_close).abs(),
        "lpc": (low - prev_close).abs(),
    }).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


def calculate_supertrend(high, low, close, period=10, multiplier=3.0, atr=None):
    # `atr` may be a pre-computed Series (same period) passed in by the
    # caller to avoid recomputing it — calculate_all_indicators() calls both
    # this and calculate_keltner_channel() with the same default period=10,
    # each independently running the same ewm() pass over the same data.
    if atr is None:
        atr = calculate_atr(high, low, close, period)
    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(index=close.index, dtype=float)
    direction = pd.Series(index=close.index, dtype=str)

    # ATR has a warmup period (NaN for the first `period` rows, by design in
    # calculate_atr's min_periods=period) — seeding supertrend from
    # lower_band.iloc[0] when atr.iloc[0] is still NaN previously made the
    # very first value NaN, and the recurrence's "else" branch
    # (supertrend.iloc[i] = prev_st) then propagated that NaN forward
    # through the ENTIRE remaining series whenever price stayed inside the
    # (also-NaN) bands during warmup — supertrend/supertrend_direction were
    # silently None for many asset/timeframe combos until this fix. Skip to
    # the first row where ATR (and therefore the bands) are actually valid.
    valid = atr.notna()
    if not valid.any():
        return supertrend, direction  # no valid ATR anywhere — nothing to compute
    start = valid.values.argmax()

    supertrend.iloc[start] = lower_band.iloc[start]
    direction.iloc[start] = "up"

    for i in range(start + 1, len(close)):
        prev_st = supertrend.iloc[i - 1]
        prev_dir = direction.iloc[i - 1]

        if close.iloc[i] > upper_band.iloc[i]:
            supertrend.iloc[i] = lower_band.iloc[i]
            direction.iloc[i] = "up"
        elif close.iloc[i] < lower_band.iloc[i]:
            supertrend.iloc[i] = upper_band.iloc[i]
            direction.iloc[i] = "down"
        else:
            supertrend.iloc[i] = prev_st
            direction.iloc[i] = prev_dir

    return supertrend, direction


def calculate_stoch_rsi(series: pd.Series, rsi_period=14, stoch_period=14, k_period=3, d_period=3):
    rsi = calculate_rsi(series, rsi_period)
    rsi_min = rsi.rolling(stoch_period).min()
    rsi_max = rsi.rolling(stoch_period).max()
    stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
    k = stoch_rsi.rolling(k_period).mean() * 100
    d = k.rolling(d_period).mean()
    return k, d


def calculate_cci(high, low, close, period=20):
    tp = (high + low + close) / 3
    sma_tp = tp.rolling(period).mean()
    # Was tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean()))) —
    # rolling().apply() with a Python callable re-slices a Series and
    # re-enters the Python interpreter once PER WINDOW POSITION instead of
    # running a vectorized C loop, roughly 50-100x slower than the
    # numpy-native equivalent below for typical window sizes. Runs on every
    # symbol/timeframe combo in calculate_all_indicators — every scan,
    # prewarm cycle, and signal-generation pass across the whole asset
    # universe. Vectorized via a sliding-window view: mean absolute
    # deviation of each window from ITS OWN mean (matches the original
    # semantics exactly, not an approximation via rolling std).
    mean_dev = _rolling_mean_abs_dev(tp, period)
    return (tp - sma_tp) / (0.015 * mean_dev)


def _rolling_mean_abs_dev(series: pd.Series, period: int) -> pd.Series:
    """Vectorized rolling mean absolute deviation (each window's mean
    absolute deviation from its own mean) — numpy sliding-window-view based,
    no per-window Python callback."""
    values = series.to_numpy(dtype=float)
    n = len(values)
    result = np.full(n, np.nan)
    if n >= period:
        windows = np.lib.stride_tricks.sliding_window_view(values, period)
        window_means = windows.mean(axis=1, keepdims=True)
        result[period - 1:] = np.abs(windows - window_means).mean(axis=1)
    return pd.Series(result, index=series.index)


def calculate_roc(series: pd.Series, period=12) -> pd.Series:
    return ((series - series.shift(period)) / series.shift(period)) * 100


def calculate_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff())
    obv = (direction * volume).fillna(0).cumsum()
    return obv


def calculate_cmf(high, low, close, volume, period=20):
    clv = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    cmf = (clv * volume).rolling(period).sum() / volume.rolling(period).sum()
    return cmf


def calculate_vwap(high, low, close, volume):
    tp = (high + low + close) / 3
    return (tp * volume).cumsum() / volume.cumsum()


def calculate_keltner_channel(high, low, close, ema_period=20, atr_period=10, multiplier=2.0, atr=None):
    ema = calculate_ema(close, ema_period)
    if atr is None:
        atr = calculate_atr(high, low, close, atr_period)
    upper = ema + multiplier * atr
    lower = ema - multiplier * atr
    return upper, ema, lower


def calculate_ichimoku(high, low, close):
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    chikou = close.shift(-26)
    return tenkan, kijun, senkou_a, senkou_b, chikou


def calculate_all_indicators(df: pd.DataFrame) -> dict:
    """Calculate all indicators for a given OHLCV dataframe."""
    if len(df) < 30:
        return {}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"] if "volume" in df.columns else pd.Series(0, index=df.index)

    n = len(df)
    ema9   = calculate_ema(close, 9)   if n >= 9   else close
    ema20  = calculate_ema(close, 20)  if n >= 20  else close
    ema21  = calculate_ema(close, 21)  if n >= 21  else close
    ema50  = calculate_ema(close, 50)  if n >= 50  else ema20
    ema100 = calculate_ema(close, 100) if n >= 100 else ema50
    ema200 = calculate_ema(close, 200) if n >= 200 else ema100
    sma20  = calculate_sma(close, 20)  if n >= 20  else close
    sma50  = calculate_sma(close, 50)  if n >= 50  else sma20

    macd_line, macd_signal, macd_hist = calculate_macd(close)
    bb_upper, bb_mid, bb_lower, bb_width = calculate_bollinger_bands(close)
    stoch_k, stoch_d = calculate_stoch_rsi(close)
    # calculate_supertrend's default period and calculate_keltner_channel's
    # default atr_period are both 10 — compute ATR(10) once and share it
    # instead of each function independently running the same ewm() pass.
    atr10 = calculate_atr(high, low, close, 10)
    supertrend_val, supertrend_dir = calculate_supertrend(high, low, close, atr=atr10)
    tenkan, kijun, senkou_a, senkou_b, _ = calculate_ichimoku(high, low, close)
    kc_upper, kc_mid, kc_lower = calculate_keltner_channel(high, low, close, atr=atr10)

    idx = -1
    return {
        "ema9": _safe(ema9, idx),
        "ema21": _safe(ema21, idx),
        "ema20": _safe(ema20, idx),
        "ema50": _safe(ema50, idx),
        "ema100": _safe(ema100, idx),
        "ema200": _safe(ema200, idx),
        "sma20": _safe(sma20, idx),
        "sma50": _safe(sma50, idx),
        "vwap": _safe(calculate_vwap(high, low, close, volume), idx),
        "supertrend": _safe(supertrend_val, idx),
        "supertrend_direction": supertrend_dir.iloc[idx] if len(supertrend_dir) else "up",
        "ichimoku_tenkan": _safe(tenkan, idx),
        "ichimoku_kijun": _safe(kijun, idx),
        "ichimoku_senkou_a": _safe(senkou_a, idx),
        "ichimoku_senkou_b": _safe(senkou_b, idx),
        "rsi": _safe(calculate_rsi(close), idx),
        "macd": _safe(macd_line, idx),
        "macd_signal": _safe(macd_signal, idx),
        "macd_hist": _safe(macd_hist, idx),
        "stoch_rsi_k": _safe(stoch_k, idx),
        "stoch_rsi_d": _safe(stoch_d, idx),
        "cci": _safe(calculate_cci(high, low, close), idx),
        "roc": _safe(calculate_roc(close), idx),
        "atr": _safe(calculate_atr(high, low, close), idx),
        "bb_upper": _safe(bb_upper, idx),
        "bb_middle": _safe(bb_mid, idx),
        "bb_lower": _safe(bb_lower, idx),
        "bb_width": _safe(bb_width, idx),
        "keltner_upper": _safe(kc_upper, idx),
        "keltner_lower": _safe(kc_lower, idx),
        "obv": _safe(calculate_obv(close, volume), idx),
        "cmf": _safe(calculate_cmf(high, low, close, volume), idx),
    }


def _safe(series, idx):
    try:
        val = series.iloc[idx]
        return None if (val is None or (isinstance(val, float) and np.isnan(val))) else round(float(val), 6)
    except Exception:
        return None
