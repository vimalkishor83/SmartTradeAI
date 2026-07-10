from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import get_jwt_identity
from app.extensions import db
from app.models.portfolio import Portfolio, PortfolioItem
from app.models.asset import Asset
from app.auth.decorators import login_required
from app.services.data.fetcher import market_fetcher
from datetime import datetime
import pandas as pd
import csv
import io

portfolio_bp = Blueprint("portfolio", __name__)


def _get_user_portfolio(user_id):
    p = Portfolio.query.filter_by(user_id=user_id).first()
    if not p:
        p = Portfolio(user_id=user_id, name="My Portfolio")
        db.session.add(p)
        db.session.commit()
    return p


@portfolio_bp.route("/", methods=["GET"])
@login_required
def get_portfolio():
    user_id = get_jwt_identity()
    portfolio = _get_user_portfolio(user_id)
    items = portfolio.items.all()

    # Refresh prices
    holdings = []
    total_invested = 0
    total_current = 0

    for item in items:
        if item.asset:
            df = market_fetcher.fetch(item.asset, "1d", 2)
            if df is not None and not df.empty:
                item.current_price = float(df["close"].iloc[-1])
                db.session.add(item)
        total_invested += item.invested_value
        total_current += item.current_value
        holdings.append(item.to_dict())

    db.session.commit()

    return jsonify({
        "portfolio": {
            "name": portfolio.name,
            "capital": portfolio.capital,
            "total_invested": round(total_invested, 2),
            "total_current": round(total_current, 2),
            "total_pnl": round(total_current - total_invested, 2),
            "total_pnl_pct": round((total_current - total_invested) / total_invested * 100, 2) if total_invested else 0,
        },
        "holdings": holdings,
    }), 200


@portfolio_bp.route("/add", methods=["POST"])
@login_required
def add_position():
    user_id = get_jwt_identity()
    data = request.get_json()
    portfolio = _get_user_portfolio(user_id)

    asset = Asset.query.filter_by(symbol=data.get("symbol")).first()
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    try:
        quantity = float(data.get("quantity"))
        buy_price = float(data.get("buy_price"))
    except (TypeError, ValueError):
        return jsonify({"error": "quantity and buy_price must be numbers"}), 400

    if quantity <= 0 or buy_price <= 0:
        return jsonify({"error": "quantity and buy_price must be greater than zero"}), 400

    item = PortfolioItem(
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        quantity=quantity,
        buy_price=buy_price,
        stop_loss=data.get("stop_loss"),
        target=data.get("target"),
        notes=data.get("notes"),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@portfolio_bp.route("/<int:item_id>", methods=["DELETE"])
@login_required
def remove_position(item_id):
    user_id = get_jwt_identity()
    item = PortfolioItem.query.join(Portfolio).filter(
        PortfolioItem.id == item_id, Portfolio.user_id == user_id
    ).first_or_404()
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "Position removed"}), 200


@portfolio_bp.route("/export/csv", methods=["GET"])
@login_required
def export_portfolio_csv():
    """Export portfolio holdings as CSV."""
    user_id   = get_jwt_identity()
    portfolio = _get_user_portfolio(user_id)
    items     = portfolio.items.all()

    buf    = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Symbol","Name","Market","Qty","Buy Price","Current Price",
                     "P&L","P&L%","Buy Date","Days Held"])
    for item in items:
        asset    = item.asset
        days     = (datetime.utcnow() - item.buy_date).days if item.buy_date else ""
        pnl      = round(item.current_value - item.invested_value, 2) if item.current_price else ""
        pnl_pct  = round((item.current_value - item.invested_value) / item.invested_value * 100, 2) \
                   if item.current_price and item.invested_value else ""
        writer.writerow([
            asset.symbol if asset else "",
            asset.name if asset else "",
            asset.market if asset else "",
            item.quantity,
            item.buy_price,
            item.current_price or "",
            pnl,
            pnl_pct,
            item.buy_date.strftime("%Y-%m-%d") if item.buy_date else "",
            days,
        ])

    today = datetime.utcnow().strftime("%Y-%m-%d")
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=portfolio_{today}.csv"},
    )
