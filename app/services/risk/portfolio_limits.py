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


def evaluate_order_for_user(user_id, *, size, price, stop_price=None, symbol=None):
    """Evaluate a proposed order against the user's stored portfolio limits."""
    from datetime import datetime

    from sqlalchemy import func

    from app.extensions import db
    from app.models.asset import Asset
    from app.models.journal import JournalEntry
    from app.models.portfolio import Portfolio
    from app.models.risk_limit import RiskLimit

    # Serialize risk reservations for this user. The lock is held until the
    # order request is committed, so concurrent orders cannot both pass based
    # on the same pre-order snapshot.
    limits = RiskLimit.query.filter_by(user_id=user_id).with_for_update().first()
    if not limits or not limits.enabled:
        return {"allowed": True, "checks": [], "reason": None}

    portfolio = Portfolio.query.filter_by(user_id=user_id).first()
    current_exposure = 0.0
    current_open_risk = 0.0
    drawdown_pct = 0.0
    current_correlated_exposure = 0.0
    if portfolio:
        items = list(portfolio.items)
        current_exposure = sum(float(item.current_value or 0) for item in items)
        current_open_risk = sum(
            abs(float(item.current_price or item.buy_price) - float(item.stop_loss)) * abs(float(item.quantity))
            for item in items if item.stop_loss is not None
        )
        capital = float(portfolio.capital or 0)
        if capital > 0:
            drawdown_pct = max(0.0, (capital - current_exposure) / capital * 100)

    # JournalEntry.trade_date has no server-side timezone normalization --
    # it's a plain client-supplied date (frontend/templates/dashboard/
    # journal.html defaults the date picker via
    # `new Date().toISOString().slice(0,10)`, which is always the UTC
    # calendar date regardless of the browser's local timezone). A prior
    # change here compared trade_date against a SCHEDULER_TIMEZONE-based
    # "business date" instead, which silently stopped matching any
    # journal entry once the scheduler's local date diverged from the UTC
    # date. Comparing against the same UTC date convention trade_date
    # actually uses is what keeps this check able to find "today's"
    # entries at all.
    today_loss = db.session.query(func.coalesce(func.sum(JournalEntry.pnl_amount), 0)).filter(
        JournalEntry.user_id == user_id,
        JournalEntry.trade_date == datetime.utcnow().date(),
        JournalEntry.pnl_amount < 0,
    ).scalar()
    daily_loss = abs(float(today_loss or 0))

    order_asset = Asset.query.filter_by(symbol=symbol.upper()).first() if symbol else None
    if order_asset and portfolio:
        current_correlated_exposure = sum(
            float(item.current_value or 0)
            for item in portfolio.items
            if item.asset and item.asset.market == order_asset.market
        )

    notional = float(size) * float(price or 0)
    proposed_open_risk = abs(float(price or 0) - float(stop_price or price or 0)) * float(size)
    from app.models.trading_order import TradeRequest
    reservations = db.session.query(
        func.coalesce(func.sum(TradeRequest.requested_exposure), 0),
        func.coalesce(func.sum(TradeRequest.requested_open_risk), 0),
    ).filter(
        TradeRequest.user_id == user_id,
        TradeRequest.mode == "live",
        TradeRequest.status.in_(["pending", "reconciliation_required"]),
    ).one()
    reserved_exposure = float(reservations[0] or 0)
    reserved_open_risk = float(reservations[1] or 0)
    return evaluate_limits(
        limits,
        current_exposure=current_exposure + reserved_exposure,
        proposed_exposure=notional,
        open_risk=current_open_risk + reserved_open_risk + proposed_open_risk,
        daily_loss=daily_loss,
        drawdown_pct=drawdown_pct,
        correlated_exposure=current_correlated_exposure,
    )
