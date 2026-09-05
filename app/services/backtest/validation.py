"""Request validation shared by the two backtesting API surfaces."""
from __future__ import annotations

from math import isfinite

from app.services.markets import MARKET_KEYS
from app.services.platform_config import FETCHABLE_TIMEFRAMES


BACKTEST_TIMEFRAMES = frozenset(FETCHABLE_TIMEFRAMES)
MAX_BACKTEST_DAYS = 3650
MAX_INITIAL_CAPITAL = 1_000_000_000.0
MAX_PORTFOLIO_ASSETS = 50
MAX_BACKTEST_COST = 0.01


def _integer(value, field: str, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field} must be an integer")
    if result < minimum or result > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return result


def _number(value, field: str, *, default: float, minimum: float, maximum: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field} must be a number")
    if not isfinite(result):
        raise ValueError(f"{field} must be finite")
    if result < minimum or result > maximum:
        raise ValueError(f"{field} must be between {minimum:g} and {maximum:g}")
    return result


def parse_timeframe(value: object = None, *, default: str = "1h") -> str:
    timeframe = default if value is None else value
    if not isinstance(timeframe, str) or timeframe not in BACKTEST_TIMEFRAMES:
        allowed = ", ".join(FETCHABLE_TIMEFRAMES)
        raise ValueError(f"timeframe must be one of {allowed}")
    return timeframe


def parse_days(value: object = None, *, default: int = 60) -> int:
    return _integer(value, "days", default=default, minimum=1, maximum=MAX_BACKTEST_DAYS)


def parse_initial_capital(value: object = None, *, default: float = 100_000.0) -> float:
    return _number(
        value, "initial_capital", default=default, minimum=0.01, maximum=MAX_INITIAL_CAPITAL,
    )


def parse_cost(value: object, field: str, *, default: float) -> float:
    return _number(value, field, default=default, minimum=0.0, maximum=MAX_BACKTEST_COST)


def parse_asset_id(value: object = None) -> int | None:
    if value in (None, ""):
        return None
    return _integer(value, "asset_id", default=0, minimum=1, maximum=2_147_483_647)


def parse_portfolio_limit(value: object = None, *, default: int = 15) -> int:
    return _integer(
        value, "limit", default=default, minimum=1, maximum=MAX_PORTFOLIO_ASSETS,
    )


def parse_market(value: object = None) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or value not in MARKET_KEYS:
        raise ValueError(f"market must be one of {', '.join(MARKET_KEYS)}")
    return value


def parse_symbol(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("symbol is required")
    symbol = value.strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    if len(symbol) > 30:
        raise ValueError("symbol must be 30 characters or fewer")
    return symbol


def parse_strategy_payload(data: object, *, include_windows: bool = False) -> dict:
    """Parse the JSON payload used by /backtesting/run and /walk-forward."""
    if not isinstance(data, dict):
        raise ValueError("request body must be a JSON object")

    strategy = data.get("strategy", "Default Multi-Indicator")
    if strategy is None:
        strategy = "Default Multi-Indicator"
    if not isinstance(strategy, str) or not strategy.strip():
        raise ValueError("strategy must be a non-empty string")
    if len(strategy.strip()) > 100:
        raise ValueError("strategy must be 100 characters or fewer")

    parsed = {
        "symbol": parse_symbol(data.get("symbol")),
        "timeframe": parse_timeframe(data.get("timeframe")),
        "initial_capital": parse_initial_capital(data.get("initial_capital")),
        "strategy": strategy.strip(),
        "commission": parse_cost(data.get("commission"), "commission", default=0.001),
        "slippage": parse_cost(data.get("slippage"), "slippage", default=0.0005),
    }
    if include_windows:
        parsed["n_windows"] = _integer(
            data.get("n_windows"), "n_windows", default=5, minimum=2, maximum=10,
        )
    return parsed
