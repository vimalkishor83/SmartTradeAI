"""Reconcile live order requests that outlived their HTTP request."""

from datetime import datetime, timedelta
import logging

from app.extensions import db
from app.models.trading_order import TradeRequest

logger = logging.getLogger(__name__)


def reconcile_pending_trade_requests(app):
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    with app.app_context():
        rows = TradeRequest.query.filter(
            TradeRequest.mode == "live",
            TradeRequest.status == "pending",
            TradeRequest.created_at < cutoff,
        ).order_by(TradeRequest.created_at.asc()).limit(100).all()
        for row in rows:
            try:
                from app.services.trading.delta_trading import get_configured_client
                client = get_configured_client(row.user_id)
                orders = client.get_order_history(page_size=100)
                if isinstance(orders, dict):
                    orders = orders.get("result") or orders.get("data") or orders.get("orders") or []
                if not isinstance(orders, (list, tuple)):
                    orders = []
                match = next((item for item in (orders or [])
                              if isinstance(item, dict)
                              and str(item.get("client_order_id") or "") == row.idempotency_key), None)
                if match:
                    row.status = "succeeded"
                    row.response = match
                    row.broker_order_id = str(match.get("id") or match.get("order_id") or "") or None
                else:
                    row.status = "reconciliation_required"
                    row.response = {"error": "No matching broker order found during reconciliation"}
            except Exception as exc:
                row.status = "reconciliation_required"
                row.response = {"error": "Broker history lookup failed during reconciliation"}
                logger.warning("Trade request %s reconciliation failed: %s", row.id, exc)
        if rows:
            db.session.commit()
            logger.info("Reconciled %d stale live trade request(s)", len(rows))


def register_trading_jobs(scheduler, app):
    scheduler.add_job(
        reconcile_pending_trade_requests, "interval", minutes=5,
        args=[app], id="reconcile_pending_trade_requests", replace_existing=True,
    )
