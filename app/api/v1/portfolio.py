from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import get_jwt_identity
from app.extensions import db
from app.models.portfolio import Portfolio, PortfolioItem
from app.models.asset import Asset
from app.auth.decorators import login_required
from app.services.data.fetcher import market_fetcher
from datetime import datetime
import math
import pandas as pd
import csv
import io

portfolio_bp = Blueprint("portfolio", __name__)


def _positive_float(value, field_name):
    """Return a finite positive number for portfolio financial fields."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a number")
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return number


def _optional_positive_float(value, field_name):
    if value in (None, ""):
        return None
    return _positive_float(value, field_name)


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
    # Eager-load each item's asset in the SAME query. PortfolioItem.asset is
    # lazy by default, so accessing item.asset in the loops below (executor
    # filter + to_dict()) was one extra SELECT per holding — a classic N+1.
    # joinedload collapses it to a single query.
    items = portfolio.items.options(db.joinedload(PortfolioItem.asset)).all()

    # Refresh prices in parallel instead of one sequential network round-trip
    # per holding — same anti-pattern already fixed in watchlist.py.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _current_price(item):
        asset = item.asset
        # Crypto current price is served from the Delta WS in-memory cache via
        # fetch_ticker (near-free, sub-second fresh) instead of a full Delta
        # /history/candles OHLCV round-trip just to read the last close — the
        # single biggest cost on the crypto holdings path. Non-crypto keeps the
        # OHLCV "1d" path (10-min OHLCV cache) so its behaviour is unchanged.
        if asset.market == "crypto":
            t = market_fetcher.fetch_ticker(asset)
            return float(t["price"]) if t and t.get("price") else None
        df = market_fetcher.fetch(asset, "1d", 2)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
        return None

    items_with_asset = [item for item in items if item.asset]
    price_by_item_id = {}
    if items_with_asset:
        with ThreadPoolExecutor(max_workers=min(15, len(items_with_asset))) as pool:
            futures = {pool.submit(_current_price, item): item.id for item in items_with_asset}
            for fut in as_completed(futures):
                item_id = futures[fut]
                try:
                    price = fut.result()
                    if price is not None:
                        price_by_item_id[item_id] = price
                except Exception:
                    pass

    holdings = []
    total_invested = 0
    total_current = 0

    for item in items:
        price = price_by_item_id.get(item.id)
        if price is not None:
            item.current_price = price
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
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    portfolio = _get_user_portfolio(user_id)

    symbol = (data.get("symbol") or "").strip().upper()
    asset = Asset.query.filter_by(symbol=symbol).first()
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    try:
        quantity = _positive_float(data.get("quantity"), "quantity")
        buy_price = _positive_float(data.get("buy_price"), "buy_price")
        stop_loss = _optional_positive_float(data.get("stop_loss"), "stop_loss")
        target = _optional_positive_float(data.get("target"), "target")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    item = PortfolioItem(
        portfolio_id=portfolio.id,
        asset_id=asset.id,
        quantity=quantity,
        buy_price=buy_price,
        stop_loss=stop_loss,
        target=target,
        notes=data.get("notes"),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@portfolio_bp.route("/<int:item_id>", methods=["PUT"])
@login_required
def update_position(item_id):
    # Stop loss / target were only ever settable at Add Position time — a
    # position opened without a stop (or one that needs trailing up as it
    # moves) had no way to record that afterwards, which also meant the
    # portfolio's aggregate "capital at risk" figure could never be trusted.
    user_id = get_jwt_identity()
    item = PortfolioItem.query.join(Portfolio).filter(
        PortfolioItem.id == item_id, Portfolio.user_id == user_id
    ).first_or_404()

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    if "stop_loss" in data:
        try:
            item.stop_loss = _optional_positive_float(data["stop_loss"], "stop_loss")
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    if "target" in data:
        try:
            item.target = _optional_positive_float(data["target"], "target")
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    db.session.commit()
    return jsonify(item.to_dict()), 200


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
    # Same joinedload the list endpoint above already uses — the row loop reads
    # item.asset for every holding, which without this lazy-loads one SELECT
    # per row.
    items     = portfolio.items.options(db.joinedload(PortfolioItem.asset)).all()

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
