"""Reproducibility metadata for persisted live signals.

Signal generation is also used inside candle-by-candle backtests, so the
metadata is built at the persistence boundary rather than inside the engine.
That keeps the backtest hot path free from an unnecessary O(n) data hash while
still recording the exact frame used for each live Signal row.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from app.services.backtesting.reproducibility import data_fingerprint


SIGNAL_ENGINE_VERSION = "signal-engine-v1"
RULE_BASED_MODEL_VERSION = "not_applicable"


def _database_datetime(value):
    """Return a timezone-naive UTC datetime accepted by SQLAlchemy DateTime."""
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def build_signal_provenance(
    df: pd.DataFrame,
    *,
    source: str,
    model_version: str | None = None,
) -> dict:
    """Build the immutable source metadata stored with a generated Signal."""
    frame = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    fingerprint = None
    if not frame.empty:
        try:
            fingerprint = data_fingerprint(frame)
        except Exception:
            # Provenance must never prevent a valid market signal from being
            # stored if a provider returns an unusual index or dtype.
            fingerprint = None

    return {
        "generation_source": source,
        "engine_version": SIGNAL_ENGINE_VERSION,
        "model_version": model_version or RULE_BASED_MODEL_VERSION,
        "data_fingerprint": fingerprint,
        "data_candles": int(len(frame)),
        "data_start": _database_datetime(frame.index[0]) if len(frame) else None,
        "data_end": _database_datetime(frame.index[-1]) if len(frame) else None,
    }
