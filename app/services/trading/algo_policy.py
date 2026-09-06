"""Pure validation for user-configured Delta algo execution limits."""
from decimal import Decimal, InvalidOperation
import math

from app.models.algo_trading import DEFAULT_ORDER_RULES


MAX_AMOUNT = Decimal("1000000000000")
MAX_LEVERAGE = 100
MAX_POSITIONS = 100
VALID_ORDER_TYPES = {"limit_order", "market_order"}
VALID_TIF = {None, "gtc", "ioc", "fok"}


def decimal_value(value, field, minimum=Decimal("0"), maximum=MAX_AMOUNT):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a number")
    if not result.is_finite() or result < minimum or result > maximum:
        raise ValueError(f"{field} must be between {minimum:g} and {maximum:g}")
    return result


def validate_policy_payload(data):
    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")
    mode = data.get("mode", "paper")
    if mode not in {"paper", "live"}:
        raise ValueError("mode must be 'paper' or 'live'")
    max_margin = decimal_value(data.get("max_margin_amount", 0), "max_margin_amount")
    max_notional = decimal_value(data.get("max_notional_amount", 0), "max_notional_amount")
    if max_margin <= 0 or max_notional <= 0:
        raise ValueError("max_margin_amount and max_notional_amount must be greater than zero")
    leverage = data.get("max_leverage", 1)
    if isinstance(leverage, bool) or not isinstance(leverage, int) or not 1 <= leverage <= MAX_LEVERAGE:
        raise ValueError(f"max_leverage must be an integer between 1 and {MAX_LEVERAGE}")
    positions = data.get("max_open_positions", 1)
    if isinstance(positions, bool) or not isinstance(positions, int) or not 1 <= positions <= MAX_POSITIONS:
        raise ValueError(f"max_open_positions must be an integer between 1 and {MAX_POSITIONS}")
    daily_loss = decimal_value(data.get("max_daily_loss", 0), "max_daily_loss")
    slippage = decimal_value(data.get("max_slippage_bps", 50), "max_slippage_bps", maximum=Decimal("10000"))

    supplied = data.get("order_rules", {})
    if not isinstance(supplied, dict):
        raise ValueError("order_rules must be an object")
    rules = {key: dict(value) for key, value in DEFAULT_ORDER_RULES.items()}
    for key, rule in supplied.items():
        if key not in rules or not isinstance(rule, dict):
            raise ValueError(f"unknown order rule: {key}")
        order_type = rule.get("order_type", rules[key]["order_type"])
        tif = rule.get("time_in_force", rules[key]["time_in_force"])
        if order_type not in VALID_ORDER_TYPES:
            raise ValueError(f"{key}.order_type must be market_order or limit_order")
        if tif not in VALID_TIF:
            raise ValueError(f"{key}.time_in_force is invalid")
        if order_type == "market_order" and tif == "fok":
            raise ValueError(f"{key}: FOK is not valid for market orders")
        rules[key] = {"order_type": order_type, "time_in_force": tif}

    return {
        "mode": mode,
        "enabled": bool(data.get("enabled", False)),
        "max_margin_amount": max_margin,
        "max_notional_amount": max_notional,
        "max_leverage": leverage,
        "max_open_positions": positions,
        "max_daily_loss": daily_loss,
        "max_slippage_bps": slippage,
        "order_rules": rules,
    }


def preview_order(policy, *, price, requested_size, contract_multiplier=1, leverage=1):
    """Return the safe whole-unit size under both margin and notional caps."""
    price = decimal_value(price, "price", minimum=Decimal("0.00000001"))
    multiplier = decimal_value(contract_multiplier, "contract_multiplier", minimum=Decimal("0.00000001"))
    if isinstance(requested_size, bool) or not isinstance(requested_size, int) or requested_size <= 0:
        raise ValueError("requested_size must be a positive integer")
    if isinstance(leverage, bool) or not isinstance(leverage, int) or leverage < 1 or leverage > policy.max_leverage:
        raise ValueError("requested leverage exceeds the configured maximum")
    unit_notional = price * multiplier
    by_notional = int(policy.max_notional_amount // unit_notional)
    by_margin = int((policy.max_margin_amount * Decimal(leverage)) // unit_notional)
    allowed = max(0, min(requested_size, by_notional, by_margin))
    limited_by = "both" if by_margin == by_notional else ("margin" if by_margin < by_notional else "notional")
    return {
        "requested_size": requested_size,
        "allowed_size": allowed,
        "notional_amount": float(unit_notional * allowed),
        "margin_amount": float((unit_notional * allowed) / Decimal(leverage)),
        "limited_by": limited_by,
        "blocked": allowed == 0,
    }
