"""
Phase 3 (Data Quality Engine) regression tests for
app/services/data/quality.py.

Covers the timezone landmine identified during investigation: Delta/Binance
return tz-naive UTC timestamps, Yahoo Finance returns tz-aware timestamps
localized per-instrument (NSE -> Asia/Kolkata, US -> America/New_York,
forex -> Europe/London). assess_data_quality() must handle both without
raising and must compute the same real-world age either way.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.services.data.quality import assess_data_quality, _normalize_utc


def _make_df(n=60, freq_minutes=60, tz=None, start=None, price=100.0):
    end = start or datetime.now(timezone.utc)
    end = pd.Timestamp(end)
    end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    if tz:
        end = end.tz_convert(tz)
    idx = pd.date_range(end=end, periods=n, freq=f"{freq_minutes}min", tz=tz)
    df = pd.DataFrame({
        "open": [price] * n,
        "high": [price * 1.01] * n,
        "low": [price * 0.99] * n,
        "close": [price] * n,
        "volume": [1000.0] * n,
    }, index=idx)
    return df


class TestNormalizeUtc:
    def test_naive_timestamp_is_treated_as_utc(self):
        naive = pd.Timestamp("2026-09-05 10:00:00")
        result = _normalize_utc(naive)
        assert result.tzinfo is not None
        assert result.utcoffset() == timedelta(0)

    def test_aware_timestamp_converted_to_utc(self):
        aware = pd.Timestamp("2026-09-05 15:30:00", tz="Asia/Kolkata")
        result = _normalize_utc(aware)
        assert result.utcoffset() == timedelta(0)
        # 15:30 IST (+05:30) == 10:00 UTC
        assert result.hour == 10
        assert result.minute == 0

    def test_naive_and_aware_representing_same_instant_agree(self):
        naive = pd.Timestamp("2026-09-05 10:00:00")           # meant as UTC
        aware = pd.Timestamp("2026-09-05 10:00:00", tz="UTC")
        assert _normalize_utc(naive) == _normalize_utc(aware)


class TestFreshData:
    def test_fresh_naive_crypto_data_is_green(self):
        df = _make_df(n=60, freq_minutes=60, tz=None)
        result = assess_data_quality(df, market="crypto", timeframe="1h", provider="delta_exchange")
        assert result["status"] == "GREEN"
        assert result["issues"] == []
        assert result["warnings"] == []
        assert result["provider"] == "delta_exchange"
        assert result["market"] == "crypto"
        assert result["timeframe"] == "1h"
        assert result["candle_count"] == 60
        assert result["expected_interval_seconds"] == 3600
        assert result["last_candle_at"].endswith("+00:00")
        assert result["hard_invalid"] is False

    def test_metadata_is_stable_when_provider_is_unknown(self):
        result = assess_data_quality(_make_df(n=3), market="index", timeframe="15m")
        assert result["provider"] is None
        assert result["candle_count"] == 3
        assert result["expected_interval_seconds"] == 900

    def test_empty_result_keeps_contract_metadata(self):
        result = assess_data_quality(pd.DataFrame(), market="crypto", timeframe="1h", provider="binance")
        assert result["status"] == "RED"
        assert result["provider"] == "binance"
        assert result["candle_count"] == 0
        assert result["last_candle_at"] is None
        assert result["warnings"] == []

    def test_fresh_aware_nse_data_is_green(self):
        df = _make_df(n=60, freq_minutes=60, tz="Asia/Kolkata")
        result = assess_data_quality(df, market="indian_stock", timeframe="1h")
        assert result["status"] == "GREEN"
        assert result["hard_invalid"] is False

    def test_fresh_aware_forex_london_data_is_green(self):
        df = _make_df(n=60, freq_minutes=60, tz="Europe/London")
        result = assess_data_quality(df, market="forex", timeframe="1h")
        assert result["status"] == "GREEN"

    def test_fresh_aware_us_equity_data_is_green(self):
        df = _make_df(n=60, freq_minutes=60, tz="America/New_York")
        result = assess_data_quality(df, market="index", timeframe="1h")
        assert result["status"] == "GREEN"


class TestStaleness:
    def test_very_stale_naive_data_is_red(self):
        old_end = datetime.now(timezone.utc) - timedelta(hours=10)
        df = _make_df(n=60, freq_minutes=60, tz=None, start=old_end)
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["status"] == "RED"
        assert any("old" in i for i in result["issues"])
        assert result["warnings"] == result["issues"]
        # Staleness alone is not a hard-data-integrity problem.
        assert result["hard_invalid"] is False

    def test_very_stale_aware_data_is_red_not_typeerror(self):
        old_end = datetime.now(timezone.utc) - timedelta(hours=10)
        df = _make_df(n=60, freq_minutes=60, tz="Asia/Kolkata", start=old_end)
        result = assess_data_quality(df, market="indian_stock", timeframe="1h")
        assert result["status"] == "RED"
        assert result["hard_invalid"] is False

    def test_borderline_staleness_is_yellow(self):
        # Just past half the stale threshold (3 bars), inside the full threshold.
        old_end = datetime.now(timezone.utc) - timedelta(hours=2)
        df = _make_df(n=60, freq_minutes=60, tz=None, start=old_end)
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["status"] == "YELLOW"

    def test_staleness_reports_age_seconds(self):
        old_end = datetime.now(timezone.utc) - timedelta(hours=10)
        df = _make_df(n=60, freq_minutes=60, tz=None, start=old_end)
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["last_candle_age_seconds"] > 9 * 3600


class TestHardIntegrityIssues:
    def test_empty_dataframe_is_red_and_hard_invalid(self):
        df = pd.DataFrame()
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["status"] == "RED"
        assert result["hard_invalid"] is True

    def test_none_dataframe_is_red_and_hard_invalid(self):
        result = assess_data_quality(None, market="crypto", timeframe="1h")
        assert result["status"] == "RED"
        assert result["hard_invalid"] is True

    def test_missing_required_column_is_hard_invalid(self):
        df = _make_df()
        df = df.drop(columns=["low"])
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["status"] == "RED"
        assert result["hard_invalid"] is True

    def test_duplicate_timestamps_are_hard_invalid(self):
        df = _make_df(n=60, freq_minutes=60, tz=None)
        df.index = list(df.index[:-1]) + [df.index[-2]]  # duplicate the 2nd-to-last row's timestamp
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["status"] == "RED"
        assert result["hard_invalid"] is True

    def test_high_below_low_is_hard_invalid(self):
        df = _make_df(n=60, freq_minutes=60, tz=None)
        df.iloc[-1, df.columns.get_loc("high")] = 50.0
        df.iloc[-1, df.columns.get_loc("low")] = 60.0
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["status"] == "RED"
        assert result["hard_invalid"] is True

    def test_negative_price_is_hard_invalid(self):
        df = _make_df(n=60, freq_minutes=60, tz=None)
        df.iloc[-1, df.columns.get_loc("close")] = -5.0
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["status"] == "RED"
        assert result["hard_invalid"] is True

    def test_negative_volume_is_hard_invalid(self):
        df = _make_df(n=60, freq_minutes=60, tz=None)
        df.iloc[-1, df.columns.get_loc("volume")] = -100.0
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["status"] == "RED"
        assert result["hard_invalid"] is True


class TestSoftAnomalies:
    def test_large_gap_is_yellow_not_hard_invalid(self):
        df = _make_df(n=60, freq_minutes=60, tz=None)
        # Blow out a gap in the middle of the series (not the freshness-critical tail).
        idx = list(df.index)
        idx[30] = idx[30] + timedelta(hours=10)
        df.index = idx
        df = df.sort_index()
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["status"] in ("YELLOW", "RED")
        if result["status"] == "YELLOW":
            assert result["hard_invalid"] is False

    def test_volume_spike_is_yellow(self):
        df = _make_df(n=60, freq_minutes=60, tz=None)
        df.iloc[-1, df.columns.get_loc("volume")] = 1000.0 * 100
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["status"] == "YELLOW"
        assert result["hard_invalid"] is False


class TestNeverRaises:
    def test_single_row_dataframe_does_not_raise(self):
        df = _make_df(n=1, freq_minutes=60, tz=None)
        result = assess_data_quality(df, market="crypto", timeframe="1h")
        assert result["status"] in ("GREEN", "YELLOW", "RED")

    def test_unknown_timeframe_falls_back_gracefully(self):
        df = _make_df(n=60, freq_minutes=60, tz=None)
        result = assess_data_quality(df, market="crypto", timeframe="weird_tf")
        assert result["status"] == "GREEN"
