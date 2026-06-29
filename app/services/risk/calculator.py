"""Position sizing and risk management calculator."""


def calculate_position(capital: float, risk_pct: float, entry: float,
                        stop_loss: float, lot_size: float = 1.0) -> dict:
    if not all([capital, risk_pct, entry, stop_loss]):
        return {"error": "Missing required values"}

    risk_amount = capital * (risk_pct / 100)
    risk_per_unit = abs(entry - stop_loss)

    if risk_per_unit == 0:
        return {"error": "Entry and stop loss cannot be equal"}

    units = risk_amount / risk_per_unit
    lots = units / lot_size
    position_value = units * entry
    margin_required = position_value * 0.1  # 10x leverage assumption

    return {
        "capital": capital,
        "risk_pct": risk_pct,
        "risk_amount": round(risk_amount, 2),
        "entry_price": entry,
        "stop_loss": stop_loss,
        "risk_per_unit": round(risk_per_unit, 6),
        "units": round(units, 4),
        "lots": round(lots, 4),
        "position_value": round(position_value, 2),
        "margin_required": round(margin_required, 2),
        "max_loss": round(risk_amount, 2),
    }


def calculate_risk_reward(entry: float, stop_loss: float, target: float) -> dict:
    risk = abs(entry - stop_loss)
    reward = abs(target - entry)
    rr = reward / risk if risk > 0 else 0
    return {
        "risk": round(risk, 6),
        "reward": round(reward, 6),
        "ratio": round(rr, 2),
        "label": "Good" if rr >= 2 else ("Average" if rr >= 1 else "Poor"),
    }
