"""
Position sizing and risk management calculator.

calculate_position()          — base position size from capital + risk%
calculate_position_volatility() — volatility-adjusted size (reduces in high-ATR regimes)
calculate_risk_reward()       — R:R ratio with label
"""
from __future__ import annotations

import math


def _position_input_error(capital, risk_pct, entry, stop_loss, lot_size):
    values = (capital, risk_pct, entry, stop_loss, lot_size)
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
        return "Position inputs must be finite numbers"
    if capital <= 0:
        return "Capital must be greater than zero"
    if risk_pct <= 0 or risk_pct > 100:
        return "Risk percentage must be greater than zero and no more than 100"
    if entry <= 0 or stop_loss <= 0:
        return "Entry and stop loss must be greater than zero"
    if lot_size <= 0:
        return "Lot size must be greater than zero"
    return None


def calculate_position(
    capital: float,
    risk_pct: float,
    entry: float,
    stop_loss: float,
    lot_size: float = 1.0,
) -> dict:
    """Base position sizing — fixed fractional risk model."""
    validation_error = _position_input_error(capital, risk_pct, entry, stop_loss, lot_size)
    if validation_error:
        return {"error": validation_error}

    risk_amount   = capital * (risk_pct / 100)
    risk_per_unit = abs(entry - stop_loss)

    if risk_per_unit == 0:
        return {"error": "Entry and stop loss cannot be equal"}

    units          = risk_amount / risk_per_unit
    lots           = units / lot_size
    position_value = units * entry
    margin_req     = position_value * 0.1   # 10× leverage assumption

    return {
        "capital":          capital,
        "risk_pct":         risk_pct,
        "risk_amount":      round(risk_amount, 2),
        "entry_price":      entry,
        "stop_loss":        stop_loss,
        "risk_per_unit":    round(risk_per_unit, 6),
        "units":            round(units, 4),
        "lots":             round(lots, 4),
        "position_value":   round(position_value, 2),
        "margin_required":  round(margin_req, 2),
        "max_loss":         round(risk_amount, 2),
        "volatility_regime": "normal",
        "volatility_scalar": 1.0,
    }


def calculate_position_volatility(
    capital: float,
    risk_pct: float,
    entry: float,
    stop_loss: float,
    atr: float,
    atr_lookback_values: list[float] | None = None,
    lot_size: float = 1.0,
) -> dict:
    """
    Volatility-adjusted position sizing.

    Scales the risk amount down when current ATR is elevated relative to its
    recent range (20-period ATR percentile).  This naturally reduces exposure
    during high-volatility events (news, gaps) and allows fuller size in
    calm, trending markets.

    Regime     | ATR percentile | Scalar  | Effective risk
    -----------|----------------|---------|----------------
    Normal     | ≤ 60%          | 1.00    | risk_pct × 1.00
    Elevated   | 61–80%         | 0.75    | risk_pct × 0.75
    High       | > 80%          | 0.50    | risk_pct × 0.50
    """
    if not all([capital, risk_pct, entry, stop_loss, atr]):
        return calculate_position(capital, risk_pct, entry, stop_loss, lot_size)

    validation_error = _position_input_error(capital, risk_pct, entry, stop_loss, lot_size)
    if validation_error:
        return {"error": validation_error}
    if not isinstance(atr, (int, float)) or not math.isfinite(atr) or atr < 0:
        return {"error": "ATR must be a finite number greater than or equal to zero"}

    # Determine ATR percentile within the lookback window
    if atr_lookback_values and len(atr_lookback_values) >= 5:
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
               for value in atr_lookback_values):
            return {"error": "ATR lookback values must be finite numbers greater than or equal to zero"}
        sorted_vals = sorted(atr_lookback_values)
        rank        = sum(1 for v in sorted_vals if v <= atr)
        atr_pct     = rank / len(sorted_vals)
    else:
        atr_pct = 0.5   # unknown — assume normal

    # Volatility regime and scalar
    if atr_pct > 0.80:
        regime, scalar = "high",     0.50
    elif atr_pct > 0.60:
        regime, scalar = "elevated", 0.75
    else:
        regime, scalar = "normal",   1.00

    adjusted_risk = capital * (risk_pct / 100) * scalar
    risk_per_unit = abs(entry - stop_loss)

    if risk_per_unit == 0:
        return {"error": "Entry and stop loss cannot be equal"}

    units          = adjusted_risk / risk_per_unit
    lots           = units / lot_size
    position_value = units * entry
    margin_req     = position_value * 0.1

    return {
        "capital":           capital,
        "risk_pct":          risk_pct,
        "risk_amount":       round(adjusted_risk, 2),
        "entry_price":       entry,
        "stop_loss":         stop_loss,
        "risk_per_unit":     round(risk_per_unit, 6),
        "units":             round(units, 4),
        "lots":              round(lots, 4),
        "position_value":    round(position_value, 2),
        "margin_required":   round(margin_req, 2),
        "max_loss":          round(adjusted_risk, 2),
        "volatility_regime": regime,
        "volatility_scalar": scalar,
        "atr_percentile":    round(atr_pct * 100, 1),
    }


def calculate_risk_reward(entry: float, stop_loss: float, target: float) -> dict:
    risk   = abs(entry - stop_loss)
    reward = abs(target - entry)
    rr     = reward / risk if risk > 0 else 0
    return {
        "risk":   round(risk, 6),
        "reward": round(reward, 6),
        "ratio":  round(rr, 2),
        "label":  "Good" if rr >= 2 else ("Average" if rr >= 1 else "Poor"),
    }
