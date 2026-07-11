"""
FY-wise tax report (feature 6 of this session's build) — FY-boundary
math and classification logic. Uses a lightweight stand-in object instead
of a real JournalEntry/DB row since build_tax_report only reads a few
attributes off each entry.
"""
from datetime import date
from types import SimpleNamespace

from app.services.tax.report import _fy_for_date, _classify, build_tax_report


def _entry(trade_date, market, pnl_amount, symbol="TEST"):
    return SimpleNamespace(
        trade_date=trade_date, market=market, pnl_amount=pnl_amount,
        pnl_pct=1.0, entry_price=100, exit_price=101, quantity=1, direction="BUY",
        asset=SimpleNamespace(symbol=symbol),
    )


class TestFYBoundary:
    def test_april_1_starts_new_fy(self):
        assert _fy_for_date(date(2024, 4, 1)) == "FY2024-25"

    def test_march_31_is_end_of_previous_fy(self):
        assert _fy_for_date(date(2024, 3, 31)) == "FY2023-24"

    def test_mid_year_date_in_correct_fy(self):
        assert _fy_for_date(date(2024, 12, 15)) == "FY2024-25"

    def test_january_date_belongs_to_prior_fy(self):
        # Jan 2025 is still within FY2024-25 (which runs Apr 2024 - Mar 2025)
        assert _fy_for_date(date(2025, 1, 10)) == "FY2024-25"


class TestClassification:
    def test_crypto_is_flat_rate_vda(self):
        assert _classify(_entry(date(2024, 6, 1), "crypto", 100)) == "crypto_vda"

    def test_crypto_case_insensitive(self):
        assert _classify(_entry(date(2024, 6, 1), "CRYPTO", 100)) == "crypto_vda"

    def test_equity_is_stcg(self):
        assert _classify(_entry(date(2024, 6, 1), "indian_stock", 100)) == "stcg"

    def test_forex_is_stcg(self):
        assert _classify(_entry(date(2024, 6, 1), "forex", 100)) == "stcg"

    def test_none_market_is_stcg_not_a_crash(self):
        assert _classify(_entry(date(2024, 6, 1), None, 100)) == "stcg"


class TestBuildTaxReport:
    def test_groups_entries_by_fy(self):
        entries = [
            _entry(date(2024, 5, 1), "crypto", 100),
            _entry(date(2025, 5, 1), "crypto", 200),
        ]
        report = build_tax_report(entries)
        assert set(report.keys()) == {"FY2024-25", "FY2025-26"}

    def test_crypto_and_stcg_buckets_populated_independently(self):
        entries = [
            _entry(date(2024, 5, 1), "crypto", 100),
            _entry(date(2024, 6, 1), "indian_stock", -50),
        ]
        report = build_tax_report(entries)
        fy = report["FY2024-25"]
        assert fy["crypto_vda"]["trades"] == 1
        assert fy["crypto_vda"]["realized_pnl"] == 100.0
        assert fy["stcg"]["trades"] == 1
        assert fy["stcg"]["realized_pnl"] == -50.0
        assert fy["ltcg"]["trades"] == 0  # no holding-period data — always empty, see module docstring

    def test_gains_and_losses_split_correctly(self):
        entries = [
            _entry(date(2024, 5, 1), "crypto", 300),
            _entry(date(2024, 6, 1), "crypto", -100),
        ]
        report = build_tax_report(entries)
        bucket = report["FY2024-25"]["crypto_vda"]
        assert bucket["realized_pnl"] == 200.0
        assert bucket["gains"] == 300.0
        assert bucket["losses"] == -100.0

    def test_entries_missing_pnl_or_date_are_skipped(self):
        entries = [
            _entry(date(2024, 5, 1), "crypto", None),   # no pnl -> skip
            SimpleNamespace(trade_date=None, market="crypto", pnl_amount=100,
                             pnl_pct=1, entry_price=1, exit_price=2, quantity=1,
                             direction="BUY", asset=None),  # no date -> skip
        ]
        report = build_tax_report(entries)
        assert report == {}

    def test_per_trade_entries_tagged_with_fy_and_bucket(self):
        entries = [_entry(date(2024, 5, 1), "crypto", 100, symbol="BTCUSDT")]
        report = build_tax_report(entries)
        row = report["FY2024-25"]["entries"][0]
        assert row["symbol"] == "BTCUSDT"
        assert row["fy"] == "FY2024-25"
        assert row["tax_bucket"] == "crypto_vda"
        assert row["pnl_amount"] == 100.0

    def test_empty_entries_returns_empty_report(self):
        assert build_tax_report([]) == {}
