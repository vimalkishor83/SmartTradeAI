"""Background jobs for market data, ticker updates, and signal outcome tracking."""
import logging
from app.websocket.events import broadcast_ticker

logger = logging.getLogger(__name__)


def update_tickers(app):
    """Fetch live prices for crypto assets and broadcast via WebSocket."""
    with app.app_context():
        from app.models.asset import Asset
        from app.services.data.fetcher import market_fetcher

        crypto_assets = Asset.query.filter_by(market="crypto", is_active=True, data_source="binance").all()
        for asset in crypto_assets:
            try:
                ticker = market_fetcher.fetch_ticker(asset)
                if ticker:
                    broadcast_ticker(asset.symbol, ticker)
            except Exception as e:
                logger.debug(f"Ticker update failed for {asset.symbol}: {e}")


def close_and_record_signals(app):
    """
    Check all active signals against current price.
    Close them as win/loss/expired and write to SignalHistory.
    This is what populates the win rate.
    """
    with app.app_context():
        from app.models.signal import Signal, SignalHistory
        from app.models.asset import Asset
        from app.services.data.fetcher import market_fetcher
        from app.extensions import db
        from datetime import datetime

        active = Signal.query.filter_by(status="active").all()
        closed = 0

        for signal in active:
            try:
                asset = Asset.query.get(signal.asset_id)
                if not asset:
                    continue

                # Get current price
                ticker = market_fetcher.fetch_ticker(asset)
                if not ticker or not ticker.get("price"):
                    # No price — just expire if past expiry time
                    if signal.expires_at and signal.expires_at < datetime.utcnow():
                        signal.status = "expired"
                    continue

                current_price = float(ticker["price"])
                signal.current_price = current_price

                # Determine outcome
                outcome = _check_outcome(signal, current_price)
                if outcome:
                    # Calculate P&L
                    if signal.signal_type in ("BUY", "HOLD"):
                        pnl_pct = (current_price - signal.entry_price) / signal.entry_price * 100
                    else:
                        pnl_pct = (signal.entry_price - current_price) / signal.entry_price * 100

                    signal.status = outcome
                    signal.pnl_pct = round(pnl_pct, 2)

                    # Write to history
                    history_outcome = "win" if outcome == "hit_target" else "loss" if outcome == "hit_sl" else "neutral"
                    now = datetime.utcnow()
                    duration = int((now - signal.generated_at).total_seconds() / 60) if signal.generated_at else None
                    hist = SignalHistory(
                        signal_id=signal.id,
                        asset_id=signal.asset_id,
                        timeframe=signal.timeframe,
                        signal_type=signal.signal_type,
                        entry_price=signal.entry_price,
                        exit_price=current_price,
                        stop_loss=signal.stop_loss,
                        target1=signal.target1,
                        confidence_score=signal.confidence_score,
                        outcome=history_outcome,
                        pnl_pct=round(pnl_pct, 2),
                        duration_minutes=duration,
                        generated_at=signal.generated_at,
                        closed_at=now,
                    )
                    db.session.add(hist)
                    closed += 1

            except Exception as e:
                logger.debug(f"Signal close check failed for signal {signal.id}: {e}")

        if closed:
            db.session.commit()
            logger.info(f"Closed {closed} signals with outcome")


def _check_outcome(signal, current_price):
    """Return 'hit_target', 'hit_sl', 'expired', or None (still open)."""
    from datetime import datetime

    sl  = signal.stop_loss
    t1  = signal.target1

    if signal.signal_type in ("BUY", "HOLD"):
        if t1 and current_price >= t1:
            return "hit_target"
        if sl and current_price <= sl:
            return "hit_sl"
    elif signal.signal_type in ("SELL", "EXIT"):
        if t1 and current_price <= t1:
            return "hit_target"
        if sl and current_price >= sl:
            return "hit_sl"

    # Expired by time
    if signal.expires_at and signal.expires_at < datetime.utcnow():
        return "expired"

    return None


def register_data_jobs(scheduler, app):
    # Crypto ticker — every 5 seconds
    scheduler.add_job(update_tickers, "interval", seconds=5,
                      args=[app], id="update_tickers", replace_existing=True)
    # Signal outcome tracking — every 5 minutes
    scheduler.add_job(close_and_record_signals, "interval", minutes=5,
                      args=[app], id="close_signals", replace_existing=True)
    logger.info("Data jobs registered")
