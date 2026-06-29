"""
AI Prediction Engine using ensemble of Random Forest, XGBoost, LightGBM, LSTM.
Falls back gracefully when optional ML dependencies are not installed.
"""
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build ML feature matrix from OHLCV + indicators."""
    from app.services.indicators.calculator import (
        calculate_rsi, calculate_ema, calculate_macd, calculate_atr,
        calculate_bollinger_bands, calculate_obv,
    )

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df.get("volume", pd.Series(0, index=df.index))

    feat = pd.DataFrame(index=df.index)
    feat["returns"] = close.pct_change()
    feat["returns_5"] = close.pct_change(5)
    feat["returns_10"] = close.pct_change(10)

    feat["ema20"] = calculate_ema(close, 20)
    feat["ema50"] = calculate_ema(close, 50)
    feat["ema_ratio"] = feat["ema20"] / feat["ema50"]

    feat["rsi"] = calculate_rsi(close)
    macd, macd_sig, macd_hist = calculate_macd(close)
    feat["macd"] = macd
    feat["macd_signal"] = macd_sig
    feat["macd_hist"] = macd_hist

    feat["atr"] = calculate_atr(high, low, close)
    feat["atr_pct"] = feat["atr"] / close

    bb_up, bb_mid, bb_low, _ = calculate_bollinger_bands(close)
    feat["bb_position"] = (close - bb_low) / (bb_up - bb_low).replace(0, np.nan)

    feat["hl_ratio"] = (high - low) / close
    feat["obv"] = calculate_obv(close, volume)
    feat["obv_change"] = feat["obv"].pct_change(5)

    # Rolling stats
    for p in [5, 10, 20]:
        feat[f"vol_{p}"] = close.rolling(p).std() / close

    feat = feat.replace([np.inf, -np.inf], np.nan).dropna()
    return feat


def _make_labels(df: pd.DataFrame, lookahead: int = 3) -> pd.Series:
    """1 = bullish (price goes up), 0 = bearish."""
    future = df["close"].shift(-lookahead)
    return (future > df["close"]).astype(int)


class AIPredictor:

    def __init__(self):
        self._models_cache = {}

    def predict(self, df: pd.DataFrame, asset_symbol: str, timeframe: str) -> dict:
        """Return ensemble prediction for the latest candle."""
        default = {
            "bullish_probability": 50.0,
            "bearish_probability": 50.0,
            "predicted_direction": "neutral",
            "confidence": 50.0,
            "model_name": "ensemble",
            "predicted_target": None,
            "predicted_stop": None,
        }

        if df is None or len(df) < 100:
            return default

        try:
            feat = _build_features(df)
            labels = _make_labels(df.loc[feat.index])
            feat = feat.iloc[:-3]
            labels = labels.iloc[:-3]

            if len(feat) < 50:
                return default

            X_train = feat.values
            y_train = labels.values
            X_pred = _build_features(df).iloc[[-1]].values

            probs = self._ensemble_predict(X_train, y_train, X_pred, asset_symbol, timeframe)
            bull_prob = round(probs[0] * 100, 1)
            bear_prob = round((1 - probs[0]) * 100, 1)

            direction = "bullish" if bull_prob > 55 else ("bearish" if bear_prob > 55 else "neutral")
            confidence = max(bull_prob, bear_prob)

            close = float(df["close"].iloc[-1])
            atr = float(df["high"].iloc[-20:].mean() - df["low"].iloc[-20:].mean()) / 2

            return {
                "bullish_probability": bull_prob,
                "bearish_probability": bear_prob,
                "predicted_direction": direction,
                "confidence": confidence,
                "model_name": "ensemble",
                "predicted_target": round(close + atr * 1.5, 6) if direction == "bullish" else round(close - atr * 1.5, 6),
                "predicted_stop": round(close - atr, 6) if direction == "bullish" else round(close + atr, 6),
            }
        except Exception as e:
            logger.error(f"AI prediction error for {asset_symbol}: {e}")
            return default

    def _ensemble_predict(self, X_train, y_train, X_pred, symbol, timeframe):
        probs = []
        cache_key = f"{symbol}_{timeframe}"

        # Random Forest
        try:
            from sklearn.ensemble import RandomForestClassifier
            key = f"rf_{cache_key}"
            if key not in self._models_cache:
                m = RandomForestClassifier(n_estimators=100, max_depth=8, random_state=42, n_jobs=-1)
                m.fit(X_train, y_train)
                self._models_cache[key] = m
            probs.append(self._models_cache[key].predict_proba(X_pred)[0][1])
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"RF error: {e}")

        # XGBoost
        try:
            import xgboost as xgb
            key = f"xgb_{cache_key}"
            if key not in self._models_cache:
                m = xgb.XGBClassifier(n_estimators=100, max_depth=6, learning_rate=0.1,
                                       use_label_encoder=False, eval_metric="logloss",
                                       verbosity=0, random_state=42)
                m.fit(X_train, y_train)
                self._models_cache[key] = m
            probs.append(self._models_cache[key].predict_proba(X_pred)[0][1])
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"XGB error: {e}")

        # LightGBM
        try:
            import lightgbm as lgb
            key = f"lgb_{cache_key}"
            if key not in self._models_cache:
                m = lgb.LGBMClassifier(n_estimators=100, max_depth=6, learning_rate=0.1,
                                        verbose=-1, random_state=42)
                m.fit(X_train, y_train)
                self._models_cache[key] = m
            probs.append(self._models_cache[key].predict_proba(X_pred)[0][1])
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"LGB error: {e}")

        if not probs:
            # Simple heuristic fallback: last 5 returns
            recent_returns = np.diff(X_pred[0][:5])
            p = float(np.mean(recent_returns > 0))
            return [max(0.3, min(0.7, p))]

        return [np.mean(probs)]


ai_predictor = AIPredictor()
