"""
Background monitor for ProtectiveOrder rows (stop-loss / take-profit /
trailing-stop watches on a user's own PortfolioItem holdings).

Runs on the same interval-job pattern as close_and_record_signals in
data_tasks.py: batch-fetch to avoid N+1, cache ticker price per asset,
atomically "claim" a trigger before acting on it (guards against two
overlapping job runs double-firing the same breach), notify on every
trigger, and only submit a real broker order when both auto_execute=True
and is_dry_run=False — the safe default for every ProtectiveOrder is
notify-only.
"""
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def check_protective_orders(app):
    with app.app_context():
        from app.models.protective_order import ProtectiveOrder
        from app.models.asset import Asset
        from app.services.data.fetcher import market_fetcher
        from app.extensions import db

        active = ProtectiveOrder.query.filter_by(status="active").all()
        if not active:
            return

        asset_ids = {o.asset_id for o in active}
        assets_map = {a.id: a for a in Asset.query.filter(Asset.id.in_(asset_ids)).all()}

        price_cache = {}
        triggered = 0

        for order in active:
            try:
                asset = assets_map.get(order.asset_id)
                if not asset:
                    continue

                if asset.id not in price_cache:
                    ticker = market_fetcher.fetch_ticker(asset)
                    price_cache[asset.id] = float(ticker["price"]) if ticker and ticker.get("price") else None
                current_price = price_cache[asset.id]
                if not current_price:
                    continue

                order.last_checked_price = current_price
                order.last_checked_at = datetime.utcnow()

                # Update trailing high-water mark BEFORE checking breach —
                # a trailing stop should trail the best price seen up to
                # and including this tick.
                if order.trailing_enabled:
                    _update_trailing(order, current_price)

                outcome = _check_breach(order, current_price)
                if outcome:
                    if not _claim_trigger(order, outcome):
                        continue
                    triggered += 1
                    order.trigger_price = current_price
                    order.triggered_at = datetime.utcnow()
                    _handle_trigger(order, asset, current_price, outcome, app)

            except Exception as e:
                logger.error(f"Protective order check failed for order {order.id}: {e}")

        try:
            db.session.commit()
            if triggered:
                logger.info(f"Protective orders: {triggered} triggered this run")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Protective order commit failed: {e}")


def _update_trailing(order, current_price):
    """Ratchet the high-water mark in the position's favorable direction
    only — never lets it move backward, so the trailing stop can only
    tighten, never loosen, exactly like a real trailing-stop order."""
    if order.high_water_mark is None:
        order.high_water_mark = current_price
        return
    if order.side == "long":
        if current_price > order.high_water_mark:
            order.high_water_mark = current_price
    else:  # short
        if current_price < order.high_water_mark:
            order.high_water_mark = current_price


def _check_breach(order, current_price):
    """Return 'triggered_sl', 'triggered_tp', 'triggered_trailing', or None."""
    is_long = order.side == "long"

    if order.trailing_enabled and order.high_water_mark and order.trailing_distance_pct:
        if is_long:
            trail_stop = order.high_water_mark * (1 - order.trailing_distance_pct / 100)
            if current_price <= trail_stop:
                return "triggered_trailing"
        else:
            trail_stop = order.high_water_mark * (1 + order.trailing_distance_pct / 100)
            if current_price >= trail_stop:
                return "triggered_trailing"

    if order.stop_loss:
        if is_long and current_price <= order.stop_loss:
            return "triggered_sl"
        if not is_long and current_price >= order.stop_loss:
            return "triggered_sl"

    if order.take_profit:
        if is_long and current_price >= order.take_profit:
            return "triggered_tp"
        if not is_long and current_price <= order.take_profit:
            return "triggered_tp"

    return None


def _claim_trigger(order, new_status: str) -> bool:
    """Atomic claim, same pattern as data_tasks._claim_signal_close — guards
    against two overlapping job runs both seeing status='active' and both
    trying to act on (and potentially double-execute) the same breach."""
    from app.models.protective_order import ProtectiveOrder
    from app.extensions import db

    result = db.session.execute(
        ProtectiveOrder.__table__.update()
        .where(ProtectiveOrder.id == order.id, ProtectiveOrder.status == "active")
        .values(status=new_status)
    )
    return result.rowcount > 0


def _handle_trigger(order, asset, current_price, outcome, app):
    """Notify the user always; place a real closing order only if the user
    has explicitly opted into both auto_execute and turned off dry_run."""
    label = {
        "triggered_sl": "Stop Loss Hit",
        "triggered_tp": "Take Profit Hit",
        "triggered_trailing": "Trailing Stop Hit",
    }.get(outcome, outcome)

    executed = False
    if order.auto_execute and not order.is_dry_run:
        executed = _execute_close(order, asset, current_price)
    elif order.auto_execute and order.is_dry_run:
        order.broker_order_result = json.dumps({"dry_run": True, "would_close_at": current_price})

    _notify_trigger(order, asset, current_price, label, executed)


def _execute_close(order, asset, current_price) -> bool:
    """Places a real reduce_only market order via the user's connected
    Delta client to close the position this ProtectiveOrder is watching.
    Failure here does NOT re-open the order (it stays in its triggered
    status) — it records the error so the user sees a clear "we tried to
    close this and it failed, check your position manually" state instead
    of silently retrying against a real account indefinitely."""
    from app.services.trading.delta_trading import get_configured_client, DeltaTradingError
    from app.services.data.fetcher import to_delta_symbol

    try:
        client = get_configured_client(order.user_id)
        delta_symbol = to_delta_symbol(asset.symbol)
        if not delta_symbol:
            order.error_message = f"{asset.symbol} is not a tradeable Delta Exchange symbol"
            return False

        product_id = client.get_product_id(delta_symbol)
        # Closing a long = sell; closing a short = buy.
        close_side = "sell" if order.side == "long" else "buy"
        size = int(order.portfolio_item.quantity) if order.portfolio_item else 1
        result = client.place_order(
            product_id=product_id, side=close_side, size=max(size, 1),
            order_type="market_order", reduce_only=True,
        )
        order.broker_order_result = json.dumps(result)
        return True
    except DeltaTradingError as e:
        order.error_message = str(e)
        logger.error(f"Protective order {order.id} auto-close failed: {e}")
        return False
    except Exception as e:
        order.error_message = str(e)
        logger.error(f"Protective order {order.id} auto-close failed: {e}")
        return False


def _notify_trigger(order, asset, current_price, label, executed):
    from app.models.notification import Notification
    from app.models.user import User
    from app.extensions import db

    user = User.query.get(order.user_id)
    if not user:
        return

    mode = "auto-closed" if executed else ("dry-run — no order sent" if order.auto_execute else "notify only")
    title = f"{'🛑' if 'SL' in label or 'Stop' in label else '🎯'} {label}: {asset.symbol}"
    msg = f"{asset.symbol} {order.side} position — {label} @ {current_price:.4f} ({mode})"

    db.session.add(Notification(
        user_id=user.id, title=title, message=msg,
        notification_type="protective_order_triggered", channel="web",
        asset_symbol=asset.symbol,
    ))
    try:
        from app.websocket.events import broadcast_notification
        broadcast_notification(user.id, title, msg)
    except Exception:
        pass
    if user.telegram_enabled and user.telegram_chat_id:
        try:
            from app.tasks.notification_tasks import _send_telegram
            _send_telegram(user.telegram_chat_id, f"*{title}*\n{msg}")
        except Exception:
            pass
    if user.push_enabled and user.push_subscription:
        try:
            from app.services.push import send_push_to_user
            send_push_to_user(user, title, msg, url="/portfolio")
        except Exception:
            pass


def register_protective_order_jobs(scheduler, app):
    """Runs every 60s — tighter than the 5-min signal-close cadence since a
    live SL/TP/trailing-stop watch on a real position benefits from faster
    reaction than an informational AI signal does."""
    scheduler.add_job(
        check_protective_orders, "interval", seconds=60,
        args=[app], id="check_protective_orders", replace_existing=True,
    )
