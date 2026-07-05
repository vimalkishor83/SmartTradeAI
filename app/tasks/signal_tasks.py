"""Background jobs for automatic signal generation on all timeframes."""
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import and_

logger = logging.getLogger(__name__)

# Higher timeframe to use for MTF alignment gate (Stage 3)
_HIGHER_TF = {
    "1m":  "5m",
    "5m":  "15m",
    "15m": "1h",
    "30m": "1h",
    "1h":  "4h",
    "2h":  "4h",
    "4h":  "1d",
    "1d":  None,   # no higher TF for daily
}

TIMEFRAME_INTERVALS = {
    "1m":  {"minutes": 1},
    "5m":  {"minutes": 5},
    "15m": {"minutes": 15},
    "30m": {"minutes": 30},
    "1h":  {"hours": 1},
    "2h":  {"hours": 2},
    "4h":  {"hours": 4},
    "1d":  {"hours": 24},
}


def generate_signals_for_timeframe(app, timeframe: str):
    with app.app_context():
        from app.models.asset import Asset
        from app.models.signal import Signal
        from app.extensions import db
        from app.services.signals.engine import signal_engine
        from app.services.data.fetcher import market_fetcher

        assets  = Asset.query.filter_by(is_active=True).all()
        htf     = _HIGHER_TF.get(timeframe)
        lockout = signal_engine.lockout_minutes(timeframe)

        # ── Fetch all OHLCV in parallel (current TF + higher TF) ──
        tfs_to_fetch = [timeframe] if htf is None else [timeframe, htf]
        all_data = market_fetcher.fetch_many(assets, tfs_to_fetch, limit=220)

        # ── Build set of asset IDs already signalled (avoid N+1 per asset) ──
        cutoff = datetime.utcnow() - timedelta(minutes=lockout)
        recent_asset_ids = {
            row[0] for row in db.session.query(Signal.asset_id).filter(
                Signal.timeframe == timeframe,
                Signal.status    == "active",
                Signal.generated_at >= cutoff,
            ).all()
        }

        generated = 0
        signals_to_add = []

        def _process_asset(asset):
            try:
                sym   = asset.symbol
                df    = all_data.get(sym, {}).get(timeframe)
                htf_df = all_data.get(sym, {}).get(htf) if htf else None

                if df is None or len(df) < 60:
                    return None
                if asset.id in recent_asset_ids:
                    return None

                result = signal_engine.generate_signal(df, asset, timeframe, htf_df)
                if not result or result["signal_type"] == "HOLD":
                    return None

                return result, asset
            except Exception as e:
                logger.error(f"Signal pipeline failed [{asset.symbol}/{timeframe}]: {e}")
                return None

        # ── Run all assets in parallel ──────────────────────────────
        with ThreadPoolExecutor(max_workers=min(8, len(assets))) as pool:
            futures = {pool.submit(_process_asset, asset): asset for asset in assets}
            for future in as_completed(futures, timeout=45):
                res = future.result()
                if res is None:
                    continue
                result, asset = res
                signals_to_add.append((result, asset))

        # ── Batch-write all signals in one transaction ──────────────
        if not signals_to_add:
            return

        try:
            for result, asset in signals_to_add:
                signal = Signal(
                    asset_id          = asset.id,
                    timeframe         = timeframe,
                    signal_type       = result["signal_type"],
                    entry_price       = result["entry_price"],
                    stop_loss         = result["stop_loss"],
                    target1           = result["target1"],
                    target2           = result["target2"],
                    target3           = result["target3"],
                    risk_reward       = result["risk_reward"],
                    confidence_score  = result["confidence_score"],
                    confidence_label  = result["confidence_label"],
                    trend_score       = result["trend_score"],
                    momentum_score    = result["momentum_score"],
                    volume_score      = result["volume_score"],
                    pattern_score     = result["pattern_score"],
                    ai_score          = result["ai_score"],
                    indicators        = result["indicators"],
                    patterns          = result["patterns"],
                    reasoning         = result["reasoning"],
                    regime            = result.get("regime"),
                    expires_at        = result["expires_at"],
                )
                db.session.add(signal)

            db.session.flush()

            # Broadcast new signals via WebSocket (best-effort)
            try:
                from app.websocket.events import broadcast_signal
                for signal in db.session.new:
                    if hasattr(signal, 'to_dict'):
                        broadcast_signal(signal.to_dict())
            except Exception:
                pass

            db.session.commit()
            generated = len(signals_to_add)
            logger.info(f"Generated {generated} signals for {timeframe}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Signal batch commit failed [{timeframe}]: {e}")


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
