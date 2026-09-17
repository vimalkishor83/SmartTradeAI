"""Pure portfolio-limit evaluation used by APIs and order routes."""


def evaluate_limits(limits, *, current_exposure=0.0, proposed_exposure=0.0,
                    open_risk=0.0, daily_loss=0.0, drawdown_pct=0.0,
                    correlated_exposure=0.0):
    if not limits or not limits.enabled:
        return {"allowed": True, "checks": [], "reason": None}

    checks = [
        ("max_daily_loss", float(limits.max_daily_loss or 0), abs(float(daily_loss)), "daily loss"),
        ("max_drawdown_pct", float(limits.max_drawdown_pct or 0), abs(float(drawdown_pct)), "drawdown"),
        ("max_total_exposure", float(limits.max_total_exposure or 0),
         float(current_exposure) + float(proposed_exposure), "total exposure"),
        ("max_correlated_exposure", float(limits.max_correlated_exposure or 0),
         float(correlated_exposure) + float(proposed_exposure), "correlated exposure"),
        ("max_open_risk", float(limits.max_open_risk or 0), float(open_risk), "open risk"),
    ]
    result = []
    for name, maximum, value, label in checks:
        # Zero is an explicit "not configured" value, preserving existing
        # workflows while making any configured limit a hard server check.
        passed = maximum <= 0 or value <= maximum
        result.append({"name": name, "limit": maximum, "value": value, "passed": passed})
        if not passed:
            return {"allowed": False, "checks": result, "reason": f"Portfolio {label} limit exceeded"}
    return {"allowed": True, "checks": result, "reason": None}


def evaluate_order_for_user(user_id, *, size, price, stop_price=None):
    """Evaluate a proposed order against the user's stored portfolio limits."""
    from app.models.portfolio import Portfolio
    from app.models.risk_limit import RiskLimit

    limits = RiskLimit.query.filter_by(user_id=user_id).first()
    if not limits or not limits.enabled:
        return {"allowed": True, "checks": [], "reason": None}

    portfolio = Portfolio.query.filter_by(user_id=user_id).first()
    current_exposure = 0.0
    if portfolio:
        current_exposure = sum(float(item.current_value or 0) for item in portfolio.items)
    notional = float(size) * float(price or 0)
    open_risk = abs(float(price or 0) - float(stop_price or price or 0)) * float(size)
    return evaluate_limits(
        limits,
        current_exposure=current_exposure,
        proposed_exposure=notional,
        open_risk=open_risk,
    )
