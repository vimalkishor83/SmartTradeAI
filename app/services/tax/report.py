"""
FY-wise (India, April 1 - March 31) realized-gains report built from
JournalEntry rows (the app's own trade-level P&L record). This is a
convenience export, NOT tax advice or a filing-ready computation — actual
tax liability depends on many factors (turnover, presumptive taxation
elections, set-off/carry-forward rules, etc.) this cannot know. It exists
to save a user the manual work of bucketing their own trade history by
FY and holding-period classification before handing it to a CA/filing.

Classification rules applied (per current Indian tax treatment, ~2024-25
rules, simplified):
  - market == "crypto": flat 30% flat-rate asset class (Section 115BBH) —
    no STCG/LTCG distinction, no loss set-off against other income. All
    crypto trades bucketed as "crypto_vda" regardless of holding period.
  - everything else (equity, forex, commodity, index): bucketed as STCG.
    JournalEntry stores only a single trade_date with no separate
    entry/exit date pair, so there's no holding-period data to
    distinguish LTCG (>365 days) from STCG at all -- the "ltcg" bucket is
    kept in the output shape (always zero) for schema stability, but this
    report cannot currently detect a genuine long-term equity hold. See
    _classify()'s docstring for detail; surfaced in the report/CSV
    disclaimer rather than silently guessing.
"""
from datetime import date


def _fy_for_date(d: date) -> str:
    """Indian financial year label, e.g. 2024-01-15 -> "FY2023-24" (before
    April 1) or 2024-06-01 -> "FY2024-25" (April 1 onward)."""
    if d.month >= 4:
        return f"FY{d.year}-{str(d.year + 1)[2:]}"
    return f"FY{d.year - 1}-{str(d.year)[2:]}"


def _classify(entry) -> str:
    """Return one of: crypto_vda, ltcg, stcg.

    JournalEntry stores only trade_date (a single date) with no separate
    entry/exit date pair, so there is no holding-period data to compute
    LTCG (>365 days) vs STCG from at all -- every non-crypto trade is
    classified as STCG. This is directionally correct for the overwhelming
    majority of entries in a day-trading/swing-trading journal (which is
    what this feature is built for), but a user with a genuine >1-year
    equity hold logged here would be misclassified. Flagged explicitly in
    the report/CSV disclaimer rather than silently guessing a holding
    period this model has no data to support.
    """
    market = (entry.market or "").lower()
    if market == "crypto":
        return "crypto_vda"
    return "stcg"


def build_tax_report(entries: list) -> dict:
    """
    entries: list of JournalEntry ORM objects (already filtered to the
    user and any date range by the caller).
    Returns {fy_label: {crypto_vda: {...}, ltcg: {...}, stcg: {...}}}
    plus a flat "entries" list per FY for the CSV export, each tagged
    with its fy and classification.
    """
    report: dict[str, dict] = {}

    for e in entries:
        if e.trade_date is None or e.pnl_amount is None:
            continue
        fy = _fy_for_date(e.trade_date)
        bucket = _classify(e)

        if fy not in report:
            report[fy] = {
                "crypto_vda": {"trades": 0, "realized_pnl": 0.0, "gains": 0.0, "losses": 0.0},
                "ltcg":       {"trades": 0, "realized_pnl": 0.0, "gains": 0.0, "losses": 0.0},
                "stcg":       {"trades": 0, "realized_pnl": 0.0, "gains": 0.0, "losses": 0.0},
                "entries": [],
            }

        b = report[fy][bucket]
        b["trades"] += 1
        b["realized_pnl"] += e.pnl_amount
        if e.pnl_amount >= 0:
            b["gains"] += e.pnl_amount
        else:
            b["losses"] += e.pnl_amount

        report[fy]["entries"].append({
            "trade_date": e.trade_date.isoformat(),
            "symbol": e.asset.symbol if e.asset else None,
            "market": e.market,
            "direction": e.direction,
            "entry_price": e.entry_price,
            "exit_price": e.exit_price,
            "quantity": e.quantity,
            "pnl_amount": round(e.pnl_amount, 2),
            "pnl_pct": e.pnl_pct,
            "tax_bucket": bucket,
            "fy": fy,
        })

    for fy_data in report.values():
        for bucket in ("crypto_vda", "ltcg", "stcg"):
            fy_data[bucket]["realized_pnl"] = round(fy_data[bucket]["realized_pnl"], 2)
            fy_data[bucket]["gains"] = round(fy_data[bucket]["gains"], 2)
            fy_data[bucket]["losses"] = round(fy_data[bucket]["losses"], 2)

    return report
