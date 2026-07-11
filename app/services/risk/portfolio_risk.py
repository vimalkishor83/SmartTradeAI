"""
Portfolio-level risk aggregation: correlation matrix and concentration
warnings across a user's open holdings. calculator.py only sizes a SINGLE
trade in isolation — nothing previously looked across a user's whole
portfolio to flag that, say, 5 open longs are all >0.8 correlated crypto
majors, i.e. one macro move wipes out all five at once even though each
trade was individually sized "safely".
"""
import numpy as np
import pandas as pd

# Correlation above this magnitude is flagged as a concentration risk pair
_HIGH_CORRELATION_THRESHOLD = 0.7
# A single market/asset-class holding above this % of total portfolio value
# is flagged as a concentration risk
_CONCENTRATION_PCT_THRESHOLD = 40.0


def calculate_correlation_matrix(price_history: dict[str, pd.Series]) -> dict:
    """
    price_history: {symbol: pd.Series of close prices, DatetimeIndex}
    Returns {"symbols": [...], "matrix": [[...]], "high_correlation_pairs": [...]}

    Correlation is computed on returns (pct_change), not raw price levels —
    raw-price correlation is dominated by shared long-term trend/drift and
    overstates how tightly two assets actually move together day-to-day.
    """
    symbols = list(price_history.keys())
    if len(symbols) < 2:
        return {"symbols": symbols, "matrix": [], "high_correlation_pairs": []}

    returns = {}
    for sym, prices in price_history.items():
        if prices is None or len(prices) < 3:
            continue
        returns[sym] = prices.pct_change().dropna()

    symbols = list(returns.keys())
    if len(symbols) < 2:
        return {"symbols": symbols, "matrix": [], "high_correlation_pairs": []}

    df = pd.DataFrame(returns).dropna(how="all")
    corr = df.corr()  # pairwise, NaN-tolerant by default

    matrix = corr.reindex(index=symbols, columns=symbols).values
    matrix = np.nan_to_num(matrix, nan=0.0).round(3).tolist()

    high_pairs = []
    for i, s1 in enumerate(symbols):
        for j, s2 in enumerate(symbols):
            if j <= i:
                continue
            c = matrix[i][j]
            if abs(c) >= _HIGH_CORRELATION_THRESHOLD:
                high_pairs.append({"symbol_a": s1, "symbol_b": s2, "correlation": c})
    high_pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)

    return {"symbols": symbols, "matrix": matrix, "high_correlation_pairs": high_pairs}


def calculate_concentration(holdings: list[dict]) -> dict:
    """
    holdings: [{"symbol": str, "market": str, "value": float}, ...]
    Returns per-symbol and per-market concentration %, flagging anything
    over _CONCENTRATION_PCT_THRESHOLD of total portfolio value.
    """
    total = sum(h["value"] for h in holdings if h.get("value"))
    if not total:
        return {"total_value": 0, "by_symbol": [], "by_market": [], "warnings": []}

    by_symbol = []
    for h in holdings:
        pct = (h["value"] / total * 100) if h.get("value") else 0
        by_symbol.append({"symbol": h["symbol"], "value": h["value"], "pct": round(pct, 2)})
    by_symbol.sort(key=lambda x: x["pct"], reverse=True)

    market_totals: dict[str, float] = {}
    for h in holdings:
        market_totals[h.get("market", "unknown")] = market_totals.get(h.get("market", "unknown"), 0) + (h.get("value") or 0)
    by_market = [
        {"market": m, "value": round(v, 2), "pct": round(v / total * 100, 2)}
        for m, v in sorted(market_totals.items(), key=lambda x: x[1], reverse=True)
    ]

    warnings = []
    for s in by_symbol:
        if s["pct"] >= _CONCENTRATION_PCT_THRESHOLD:
            warnings.append(f"{s['symbol']} is {s['pct']:.1f}% of your portfolio — a single-asset move has outsized impact.")
    for m in by_market:
        if m["pct"] >= _CONCENTRATION_PCT_THRESHOLD:
            warnings.append(f"{m['market']} holdings are {m['pct']:.1f}% of your portfolio — limited diversification across asset classes.")

    return {"total_value": round(total, 2), "by_symbol": by_symbol, "by_market": by_market, "warnings": warnings}
