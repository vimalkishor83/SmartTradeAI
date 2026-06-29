"""Background jobs for automatic signal generation on all timeframes."""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

TIMEFRAME_INTERVALS = {
    "1m": {"minutes": 1},
    "5m": {"minutes": 5},
    "15m": {"minutes": 15},
    "30m": {"minutes": 30},
    "1h": {"hours": 1},
    "4h": {"hours": 4},
    "1d": {"hours": 24},
}


def generate_signals_for_timeframe(app, timeframe: str):
    with app.app_context():
        from app.models.asset import Asset
        from app.models.signal import Signal
        from app.extensions import db
        from app.services.signals.engine import signal_engine
        from app.services.data.fetcher import market_fetcher
        from app.websocket.events import broadcast_signal

        assets = Asset.query.filter_by(is_active=True).all()
        generated = 0

        for asset in assets:
            try:
                df = market_fetcher.fetch(asset, timeframe, 300)
                if df is None:
                    continue

                result = signal_engine.generate_signal(df, asset, timeframe)
                if not result or result["signal_type"] == "HOLD":
                    continue

                signal = Signal(
                    asset_id=asset.id,
                    timeframe=timeframe,
                    signal_type=result["signal_type"],
                    entry_price=result["entry_price"],
                    stop_loss=result["stop_loss"],
                    target1=result["target1"],
                    target2=result["target2"],
                    target3=result["target3"],
                    risk_reward=result["risk_reward"],
                    confidence_score=result["confidence_score"],
                    confidence_label=result["confidence_label"],
                    trend_score=result["trend_score"],
                    momentum_score=result["momentum_score"],
                    volume_score=result["volume_score"],
                    pattern_score=result["pattern_score"],
                    ai_score=result["ai_score"],
                    indicators=result["indicators"],
                    patterns=result["patterns"],
                    reasoning=result["reasoning"],
                    expires_at=result["expires_at"],
                )
                db.session.add(signal)
                db.session.flush()
                broadcast_signal(signal.to_dict())
                generated += 1
            except Exception as e:
                logger.error(f"Signal generation failed for {asset.symbol}/{timeframe}: {e}")

        try:
            db.session.commit()
            logger.info(f"Generated {generated} signals for {timeframe}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Commit failed for {timeframe} signals: {e}")


def register_signal_jobs(scheduler, app):
    for timeframe, interval in TIMEFRAME_INTERVALS.items():
        scheduler.add_job(
            generate_signals_for_timeframe,
            "interval",
            args=[app, timeframe],
            id=f"signals_{timeframe}",
            replace_existing=True,
            **interval,
        )
    logger.info("Signal generation jobs registered")
