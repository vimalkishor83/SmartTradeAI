"""
AI Prediction Engine — ensemble of Random Forest, XGBoost, LightGBM.

Phase 5 improvements:
- Feature engineering: volume profile, volatility regime, time-of-day, Stochastic RSI
- Walk-forward validation: rolling train window avoids look-ahead bias
- Confidence calibration: isotonic regression (CalibratedClassifierCV) on held-out set
- Inference caching: per-symbol+TF prediction cache (TTL = candle period)
- Model staleness: retrain when model file > 24 h old
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_MODEL_DIR = Path(__file__).parent.parent.parent.parent / "data" / "models"
_MODEL_DIR.mkdir(parents=True, exist_ok=True)

_RETRAIN_AFTER      = 86400   # 24 h — retrain if model file older than this
_MIN_TRAIN_ROWS     = 100     # minimum rows after feature engineering
_DIRECTION_THRESHOLD = 0.60   # bull/bear prob must exceed this to fire

# In-process prediction cache TTL per timeframe (seconds)
_PRED_TTL = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"2h":7200,"4h":14400,"1d":86400}


# ─────────────────────────────────────────────────────────────────────────────
# Feature engineering
# ─────────────────────────────────────────────────────────────────────────────
def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Feature groups:
    1.  Price returns at 1/3/5/10 bars (momentum)
    2.  EMA ratios 20/50/100 (trend alignment)
    3.  RSI + lags (momentum state)
    4.  MACD histogram + cross (trend momentum)
    5.  ATR % of price + ATR ratio to 20-period mean (volatility regime)
    6.  Bollinger Band position [0–1] (mean-reversion)
    7.  Candle body / wick ratios (microstructure)
    8.  OBV % change 5/10 bars (volume trend)
    9.  Rolling volatility 5/10/20 (regime)
    10. Lagged returns/RSI (autocorrelation)
    11. Volume profile: volume z-score, volume vs 20-bar mean (NEW Phase 5)
    12. Volatility regime: HV20/HV5 ratio, Parkinson range estimator (NEW Phase 5)
    13. Time-of-day / day-of-week (NEW Phase 5, only if datetime index)
    14. Stochastic RSI K/D (NEW Phase 5)
    """
    from app.services.indicators.calculator import (
        calculate_rsi, calculate_ema, calculate_macd,
        calculate_atr, calculate_bollinger_bands, calculate_obv,
    )

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    open_  = df["open"]
    volume = df.get("volume", pd.Series(0.0, index=df.index))

    feat = pd.DataFrame(index=df.index)

    # ── 1. Returns ──────────────────────────────────────────
    feat["ret_1"]  = close.pct_change(1)
    feat["ret_3"]  = close.pct_change(3)
    feat["ret_5"]  = close.pct_change(5)
    feat["ret_10"] = close.pct_change(10)

    # ── 2. EMA ratios ───────────────────────────────────────
    ema20  = calculate_ema(close, 20)
    ema50  = calculate_ema(close, 50)
    ema100 = calculate_ema(close, 100)
    feat["ema_ratio_20_50"]   = ema20 / ema50
    feat["ema_ratio_50_100"]  = ema50 / ema100
    feat["price_vs_ema20"]    = close / ema20
    feat["price_vs_ema50"]    = close / ema50

    # ── 3. RSI + lags ───────────────────────────────────────
    rsi = calculate_rsi(close)
    feat["rsi"]       = rsi / 100.0
    feat["rsi_lag1"]  = rsi.shift(1) / 100.0
    feat["rsi_lag2"]  = rsi.shift(2) / 100.0
    feat["rsi_delta"] = feat["rsi"] - feat["rsi_lag1"]

    # ── 4. MACD ─────────────────────────────────────────────
    macd, macd_sig, macd_hist = calculate_macd(close)
    feat["macd_hist"]      = macd_hist
    feat["macd_hist_lag1"] = macd_hist.shift(1)
    feat["macd_cross"]     = (macd - macd_sig).apply(lambda x: 1 if x > 0 else -1)

    # ── 5. ATR ──────────────────────────────────────────────
    atr = calculate_atr(high, low, close)
    feat["atr_pct"]   = atr / close
    feat["atr_ratio"] = atr / atr.rolling(20).mean()

    # ── 6. Bollinger Band position ──────────────────────────
    bb_up, _, bb_low, _ = calculate_bollinger_bands(close)
    bb_range = (bb_up - bb_low).replace(0, np.nan)
    feat["bb_position"] = (close - bb_low) / bb_range

    # ── 7. Candle microstructure ────────────────────────────
    body    = (close - open_).abs()
    range_  = (high - low).replace(0, np.nan)
    feat["body_ratio"]       = body / range_
    feat["upper_wick_ratio"] = (high - close.combine(open_, max)) / range_
    feat["lower_wick_ratio"] = (close.combine(open_, min) - low) / range_

    # ── 8. OBV ──────────────────────────────────────────────
    obv = calculate_obv(close, volume)
    feat["obv_change_5"]  = obv.pct_change(5)
    feat["obv_change_10"] = obv.pct_change(10)

    # ── 9. Rolling volatility ────────────────────────────────
    for p in [5, 10, 20]:
        feat[f"vol_{p}"] = close.rolling(p).std() / close

    # ── 10. Lagged returns ───────────────────────────────────
    feat["ret_lag1"] = feat["ret_1"].shift(1)
    feat["ret_lag2"] = feat["ret_1"].shift(2)

    # ── 11. Volume profile (Phase 5) ─────────────────────────
    vol_safe = volume.replace(0, np.nan)
    vol_mean = vol_safe.rolling(20).mean()
    vol_std  = vol_safe.rolling(20).std()
    feat["volume_zscore"]   = (vol_safe - vol_mean) / vol_std.replace(0, np.nan)
    feat["volume_vs_mean"]  = vol_safe / vol_mean       # >1 = above-average activity
    feat["volume_trend_5"]  = vol_safe.pct_change(5)    # recent volume direction
    feat["buy_vol_proxy"]   = (close > open_).astype(float) * vol_safe / vol_mean

    # ── 12. Volatility regime (Phase 5) ──────────────────────
    hv5  = close.rolling(5).std()  / close * np.sqrt(252)
    hv20 = close.rolling(20).std() / close * np.sqrt(252)
    feat["hv_ratio"]       = hv5 / hv20.replace(0, np.nan)   # >1 = regime expansion
    # Parkinson range estimator (captures intrabar vol better than close-to-close)
    ln_hl = np.log(high / low.replace(0, np.nan))
    feat["parkinson_vol"]  = ln_hl.rolling(10).mean()

    # ── 13. Time-of-day / day-of-week (Phase 5) ──────────────
    try:
        if hasattr(df.index, 'hour'):
            feat["hour_sin"] = np.sin(2 * np.pi * df.index.hour / 24)
            feat["hour_cos"] = np.cos(2 * np.pi * df.index.hour / 24)
            feat["dow_sin"]  = np.sin(2 * np.pi * df.index.dayofweek / 7)
            feat["dow_cos"]  = np.cos(2 * np.pi * df.index.dayofweek / 7)
    except Exception:
        pass

    # ── 14. Stochastic RSI (Phase 5) ─────────────────────────
    rsi_min = rsi.rolling(14).min()
    rsi_max = rsi.rolling(14).max()
    stoch_rsi_range = (rsi_max - rsi_min).replace(0, np.nan)
    stoch_k = (rsi - rsi_min) / stoch_rsi_range
    feat["stoch_k"]        = stoch_k
    feat["stoch_d"]        = stoch_k.rolling(3).mean()   # smoothed %D
    feat["stoch_cross"]    = (stoch_k - stoch_k.shift(1)).apply(lambda x: 1 if x > 0 else -1)

    feat = feat.replace([np.inf, -np.inf], np.nan).dropna()
    return feat


def _make_labels(close: pd.Series, lookahead: int = 3) -> pd.Series:
    """1 = price higher in `lookahead` candles, 0 = lower."""
    return (close.shift(-lookahead) > close).astype(int)


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward split (Phase 5)
# ─────────────────────────────────────────────────────────────────────────────
def _walk_forward_split(X: np.ndarray, y: np.ndarray, n_splits: int = 5):
    """
    Time-series aware cross-validation.
    Returns list of (train_idx, val_idx) tuples where val is always after train.
    Uses a fixed-size rolling window (most recent `window` rows as train).
    """
    n = len(X)
    # Minimum train size = 60% of total
    min_train = max(_MIN_TRAIN_ROWS, int(n * 0.6))
    step = max(1, (n - min_train) // n_splits)

    splits = []
    for i in range(n_splits):
        train_end = min_train + i * step
        val_end   = min(train_end + step, n - 1)  # -1: keep last row for prediction
        if train_end >= val_end or val_end >= n:
            break
        # Rolling window: use the last `min_train` rows before train_end
        train_start = max(0, train_end - min_train)
        splits.append((
            np.arange(train_start, train_end),
            np.arange(train_end, val_end),
        ))
    return splits


# ─────────────────────────────────────────────────────────────────────────────
# Model persistence
# ─────────────────────────────────────────────────────────────────────────────
def _model_path(key: str) -> Path:
    safe = hashlib.md5(key.encode()).hexdigest()[:12]
    return _MODEL_DIR / f"{safe}.pkl"


def _load_model(key: str):
    try:
        import joblib
        p = _model_path(key)
        if p.exists() and (time.time() - p.stat().st_mtime) < _RETRAIN_AFTER:
            return joblib.load(p)
    except Exception:
        pass
    return None


def _save_model(key: str, model):
    try:
        import joblib
        joblib.dump(model, _model_path(key))
    except Exception as e:
        logger.debug(f"Model save failed [{key}]: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Predictor
# ─────────────────────────────────────────────────────────────────────────────
class AIPredictor:

    # In-process prediction cache: key → (bull_prob, ts)
    _pred_cache: dict[str, tuple[float, float]] = {}

    def predict(self, df: pd.DataFrame, asset_symbol: str, timeframe: str) -> dict:
        """Return ensemble prediction for the latest candle."""
        _default = {
            "bullish_probability": 50.0,
            "bearish_probability": 50.0,
            "predicted_direction": "neutral",
            "confidence": 50.0,
            "model_name": "ensemble",
            "predicted_target": None,
            "predicted_stop": None,
        }

        if df is None or len(df) < 100:
            return _default

        # Check in-process TTL cache before recomputing
        cache_key = f"{asset_symbol}_{timeframe}"
        ttl = _PRED_TTL.get(timeframe, 3600)
        cached = self._pred_cache.get(cache_key)
        if cached and (time.time() - cached[1]) < ttl:
            bull_prob = cached[0]
        else:
            try:
                feat   = _build_features(df)
                labels = _make_labels(df["close"].loc[feat.index])

                X_all   = feat.values
                y_all   = labels.values
                # Drop last 3 rows — future label unknown
                X_train = X_all[:-3]
                y_train = y_all[:-3]
                X_pred  = X_all[[-1]]

                if len(X_train) < _MIN_TRAIN_ROWS:
                    return _default

                bull_prob = self._ensemble_predict(X_train, y_train, X_pred, asset_symbol, timeframe)
                self._pred_cache[cache_key] = (bull_prob, time.time())

            except Exception as e:
                logger.error(f"AI prediction error [{asset_symbol}/{timeframe}]: {e}")
                return _default

        bull_prob = round(bull_prob * 100, 1)
        bear_prob = round(100 - bull_prob, 1)

        if bull_prob >= _DIRECTION_THRESHOLD * 100:
            direction = "bullish"
        elif bear_prob >= _DIRECTION_THRESHOLD * 100:
            direction = "bearish"
        else:
            direction = "neutral"

        confidence = max(bull_prob, bear_prob)

        close = float(df["close"].iloc[-1])
        atr   = float((df["high"].iloc[-20:] - df["low"].iloc[-20:]).mean())

        return {
            "bullish_probability": bull_prob,
            "bearish_probability": bear_prob,
            "predicted_direction": direction,
            "confidence":          confidence,
            "model_name":          "ensemble+cal",
            "predicted_target":    round(close + atr * 1.5, 6) if direction == "bullish" else round(close - atr * 1.5, 6),
            "predicted_stop":      round(close - atr,       6) if direction == "bullish" else round(close + atr,       6),
        }

    def _ensemble_predict(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_pred:  np.ndarray,
        symbol:  str,
        timeframe: str,
    ) -> float:
        """
        Train (or load cached) RF + XGB + LGB, each wrapped in isotonic calibration
        fitted on a held-out walk-forward fold.
        Returns mean calibrated bullish probability.
        """
        cache_key = f"{symbol}_{timeframe}"
        probs: list[float] = []

        # Walk-forward: use last fold's val set for calibration
        splits = _walk_forward_split(X_train, y_train, n_splits=4)
        if splits:
            cal_train_idx, cal_val_idx = splits[-1]
        else:
            # Fallback: 80/20 split
            cut = int(len(X_train) * 0.8)
            cal_train_idx = np.arange(cut)
            cal_val_idx   = np.arange(cut, len(X_train))

        X_fit = X_train[cal_train_idx]
        y_fit = y_train[cal_train_idx]
        X_cal = X_train[cal_val_idx]
        y_cal = y_train[cal_val_idx]

        # ── Random Forest + isotonic calibration ──────────────
        try:
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.calibration import CalibratedClassifierCV

            key = f"rf_{cache_key}"
            m   = _load_model(key)
            if m is None:
                base = RandomForestClassifier(
                    n_estimators=200, max_depth=8, min_samples_leaf=5,
                    random_state=42, n_jobs=-1,
                )
                base.fit(X_fit, y_fit)
                # Calibrate on the held-out fold (isotonic for better calibration on small sets)
                if len(X_cal) >= 20 and len(np.unique(y_cal)) > 1:
                    try:
                        m = CalibratedClassifierCV(base, method="isotonic", cv="prefit")
                        m.fit(X_cal, y_cal)
                    except Exception:
                        m = base
                else:
                    m = base
                _save_model(key, m)
            probs.append(m.predict_proba(X_pred)[0][1])
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"RF predict error: {e}")

        # ── XGBoost + isotonic calibration ────────────────────
        try:
            import xgboost as xgb
            from sklearn.calibration import CalibratedClassifierCV

            key = f"xgb_{cache_key}"
            m   = _load_model(key)
            if m is None:
                base = xgb.XGBClassifier(
                    n_estimators=200, max_depth=6, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8,
                    eval_metric="logloss", verbosity=0, random_state=42,
                )
                base.fit(X_fit, y_fit)
                if len(X_cal) >= 20 and len(np.unique(y_cal)) > 1:
                    try:
                        m = CalibratedClassifierCV(base, method="isotonic", cv="prefit")
                        m.fit(X_cal, y_cal)
                    except Exception:
                        m = base
                else:
                    m = base
                _save_model(key, m)
            probs.append(m.predict_proba(X_pred)[0][1])
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"XGB predict error: {e}")

        # ── LightGBM + isotonic calibration ───────────────────
        try:
            import lightgbm as lgb
            from sklearn.calibration import CalibratedClassifierCV

            key = f"lgb_{cache_key}"
            m   = _load_model(key)
            if m is None:
                base = lgb.LGBMClassifier(
                    n_estimators=200, max_depth=6, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8,
                    verbose=-1, random_state=42,
                )
                base.fit(X_fit, y_fit)
                if len(X_cal) >= 20 and len(np.unique(y_cal)) > 1:
                    try:
                        m = CalibratedClassifierCV(base, method="isotonic", cv="prefit")
                        m.fit(X_cal, y_cal)
                    except Exception:
                        m = base
                else:
                    m = base
                _save_model(key, m)
            probs.append(m.predict_proba(X_pred)[0][1])
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"LGB predict error: {e}")

        if probs:
            return float(np.mean(probs))

        return self._heuristic_fallback(X_pred[0])

    def _heuristic_fallback(self, features: np.ndarray) -> float:
        """
        Rule-based probability when no ML library is installed.
        Returns probability in [0.35, 0.65].
        """
        try:
            ret_1     = features[0]
            ret_3     = features[1]
            ema_ratio = features[4]
            rsi_norm  = features[7]

            score  = 0.0
            score += 0.3 if ret_1 > 0 else -0.3
            score += 0.2 if ret_3 > 0 else -0.2
            score += 0.3 if ema_ratio > 1.0 else -0.3
            score += 0.2 if rsi_norm > 0.5 else -0.2
            return max(0.35, min(0.65, 0.50 + score * 0.15))
        except Exception:
            return 0.50

    def invalidate_cache(self, asset_symbol: str = None, timeframe: str = None):
        """Clear in-process prediction cache (call after model retrain)."""
        if asset_symbol and timeframe:
            self._pred_cache.pop(f"{asset_symbol}_{timeframe}", None)
        elif asset_symbol:
            for k in list(self._pred_cache):
                if k.startswith(asset_symbol + "_"):
                    del self._pred_cache[k]
        else:
            self._pred_cache.clear()

    def has_ready_model(self, asset_symbol: str, timeframe: str) -> bool:
        """True if a prediction can be served WITHOUT training inline — i.e. the
        in-process prediction cache is warm, or a fresh (< _RETRAIN_AFTER) model
        file already exists on disk. Used by the API to stay non-blocking: if this
        returns False, the endpoint returns a fast 'warming up' response and lets
        the background prewarm job train the model instead of blocking the request."""
        cache_key = f"{asset_symbol}_{timeframe}"
        cached = self._pred_cache.get(cache_key)
        if cached and (time.time() - cached[1]) < _PRED_TTL.get(timeframe, 3600):
            return True
        for prefix in ("rf_", "xgb_", "lgb_"):
            p = _model_path(f"{prefix}{cache_key}")
            try:
                if p.exists() and (time.time() - p.stat().st_mtime) < _RETRAIN_AFTER:
                    return True
            except Exception:
                pass
        return False

    def force_retrain(self, asset_symbol: str, timeframe: str):
        """Delete cached model files for a symbol+TF, forcing retrain on next predict()."""
        cache_key = f"{asset_symbol}_{timeframe}"
        for prefix in ("rf_", "xgb_", "lgb_"):
            p = _model_path(f"{prefix}{cache_key}")
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        self.invalidate_cache(asset_symbol, timeframe)


ai_predictor = AIPredictor()
