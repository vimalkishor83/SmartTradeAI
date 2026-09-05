"""Stable provenance metadata for strategy backtests.

Backtest numbers are only useful when a user can identify the exact strategy
configuration and candle dataset that produced them. The current engines are
deterministic rule-based systems, so model_version is explicitly marked as
not applicable instead of implying an ML model was involved.
"""
from __future__ import annotations

from hashlib import sha256
import json

import pandas as pd


BACKTEST_ENGINE_VERSION = "strategy-backtest-v2"
LIVE_WALK_FORWARD_ENGINE_VERSION = "live-signal-walkforward-v1"
MODEL_VERSION = "not_applicable"


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def config_fingerprint(
    *,
    strategy: str,
    timeframe: str,
    initial_capital: float,
    commission: float,
    slippage: float,
    spread: float = 0.0,
    extra: dict | None = None,
) -> str:
    """Hash only canonical inputs that affect a backtest calculation."""
    payload = {
        "strategy": strategy,
        "timeframe": timeframe,
        "initial_capital": float(initial_capital),
        "commission": float(commission),
        "slippage": float(slippage),
        "spread": float(spread),
        **(extra or {}),
    }
    return _fingerprint(payload)


def data_fingerprint(df: pd.DataFrame) -> str:
    """Hash the ordered OHLCV rows and index used by the engine."""
    columns = [column for column in ("open", "high", "low", "close", "volume") if column in df.columns]
    frame = df.loc[:, columns]
    digest = sha256()
    digest.update(json.dumps(columns, separators=(",", ":")).encode("utf-8"))
    digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    return digest.hexdigest()


def _index_value(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def build_reproducibility_metadata(
    df: pd.DataFrame,
    *,
    strategy: str,
    timeframe: str,
    initial_capital: float,
    commission: float,
    slippage: float,
    spread: float = 0.0,
    extra_config: dict | None = None,
    engine_version: str = BACKTEST_ENGINE_VERSION,
    model_version: str = MODEL_VERSION,
) -> dict:
    """Build the common provenance contract for any successful backtest."""
    return {
        "backtest_id": None,
        "engine_version": engine_version,
        "model_version": model_version,
        "config_fingerprint": config_fingerprint(
            strategy=strategy,
            timeframe=timeframe,
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
            spread=spread,
            extra=extra_config,
        ),
        "data_fingerprint": data_fingerprint(df),
        "data_candles": int(len(df)),
        "data_start": _index_value(df.index[0]) if len(df) else None,
        "data_end": _index_value(df.index[-1]) if len(df) else None,
    }
