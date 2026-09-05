"""Background jobs for market data, ticker updates, and signal outcome tracking."""
import time
import threading
import logging
from app.websocket.events import broadcast_ticker

logger = logging.getLogger(__name__)


# ── Active-signal symbol gate ────────────────────────────────────────────────
# check_signals_for_price() fires on EVERY price tick (the Delta WS stream
# pushes several per second across all streamed crypto symbols). The vast
# majority of ticks are for symbols that have no active signal to close, yet
# each one still ran two SELECTs (asset lookup + active-signal lookup). This
# short-TTL cache of "symbols that currently have >=1 active signal" lets those
# ticks bail out with zero DB work. A newly generated signal calls
# invalidate_active_signal_symbols() so real-time monitoring starts at once;
# the 5-min close_and_record_signals job is the backstop regardless.
_active_sig_syms: dict = {"set": None, "ts": 0.0}
_active_sig_lock = threading.Lock()
_ACTIVE_SIG_SYMS_TTL = 20  # seconds


def invalidate_active_signal_symbols():
    """Force the next tick to re-read which symbols have active signals — call
    after creating/closing signals so the gate reflects the change promptly."""
    with _active_sig_lock:
        _active_sig_syms["set"] = None
        _active_sig_syms["ts"] = 0.0


def _symbols_with_active_signals() -> set:
    """Upper-cased set of asset symbols that currently have an active signal.
    Cached for a few seconds; assumes an active app context (callers hold one)."""
    now = time.time()
    with _active_sig_lock:
        cached = _active_sig_syms["set"]
        if cached is not None and now - _active_sig_syms["ts"] < _ACTIVE_SIG_SYMS_TTL:
            return cached
    from app.models.signal import Signal
    from app.models.asset import Asset
    from app.extensions import db
    rows = (db.session.query(Asset.symbol)
            .join(Signal, Signal.asset_id == Asset.id)
            .filter(Signal.status == "active")
            .distinct().all())
    syms = {r[0].upper() for r in rows}
    with _active_sig_lock:
        _active_sig_syms["set"] = syms
        _active_sig_syms["ts"] = now
    return syms


def update_tickers(app):
    """
    Fallback ticker poll for non-crypto assets (forex, indices, commodities, stocks).
    Crypto is handled by the Delta Exchange WebSocket stream — no polling needed there.
    Runs every 15s; broadcasts via WebSocket + updates live price cache.
    """
    with app.app_context():
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app.models.asset import Asset
        from app.services.data.fetcher import market_fetcher, blocked_data_markets

        # Only poll assets NOT covered by the Delta Exchange WS stream
        non_crypto = Asset.query.filter(
            Asset.is_active == True,
            Asset.market != "crypto",
        ).all()

        # Skip markets whose data feed is paused in APIConfig — otherwise
        # this 15s poll keeps hitting a feed the operator turned off.
        blocked = blocked_data_markets()
        if blocked:
            non_crypto = [a for a in non_crypto if a.market not in blocked]

        if not non_crypto:
            return

        # Was sequential — N synchronous yfinance HTTP calls back-to-back on
        # the scheduler thread every 15s. At even 20-30 assets and
        # ~300-800ms per call, one run could take 6-25+ seconds, risking
        # overlapping runs and starving the scheduler of timely execution
        # for its other jobs. Parallelized with the same ThreadPoolExecutor
        # pattern already used by fetch_many() elsewhere in this codebase.
        def _fetch(asset):
            try:
                return asset, market_fetcher.fetch_ticker(asset)
            except Exception as e:
                logger.debug(f"Ticker update failed for {asset.symbol}: {e}")
                return asset, None

        with ThreadPoolExecutor(max_workers=min(15, len(non_crypto))) as pool:
            futures = [pool.submit(_fetch, asset) for asset in non_crypto]
            for fut in as_completed(futures):
                asset, ticker = fut.result()
                if not ticker:
                    continue
                try:
                    broadcast_ticker(asset.symbol, ticker)
                    if ticker.get("price"):
                        check_signals_for_price(asset.symbol, float(ticker["price"]), app)
                except Exception as e:
                    logger.debug(f"Ticker broadcast/check failed for {asset.symbol}: {e}")


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

        # Build asset map to avoid N+1 queries
        asset_ids = {s.asset_id for s in active}
        assets_map = {a.id: a for a in Asset.query.filter(Asset.id.in_(asset_ids)).all()}

        # Cache ticker per asset to avoid duplicate calls when same asset has multiple signals
        price_cache = {}

        for signal in active:
            try:
                asset = assets_map.get(signal.asset_id)
                if not asset:
                    continue

                # Expire by time first (works without price data)
                if signal.expires_at and signal.expires_at < datetime.utcnow():
                    if _claim_signal_close(signal, "expired"):
                        closed += 1
                    continue

                # Get current price (cached per asset)
                if asset.id not in price_cache:
                    ticker = market_fetcher.fetch_ticker(asset)
                    price_cache[asset.id] = float(ticker["price"]) if ticker and ticker.get("price") else None

                current_price = price_cache[asset.id]
                if not current_price:
                    continue

                signal.current_price = current_price

                # Determine outcome
                outcome = _check_outcome(signal, current_price)
                if outcome:
                    # Atomically claim the close before writing history — if
                    # another job (the 15s real-time price checker, or a
                    # prior overlapping run of this same job) already closed
                    # this signal, rowcount is 0 and we skip recording a
                    # second, duplicate SignalHistory row for one trade.
                    if not _claim_signal_close(signal, outcome):
                        continue

                    # Calculate P&L
                    if signal.signal_type in ("BUY", "HOLD"):
                        pnl_pct = (current_price - signal.entry_price) / signal.entry_price * 100
                    else:
                        pnl_pct = (signal.entry_price - current_price) / signal.entry_price * 100

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

        try:
            db.session.commit()
            if closed:
                logger.info(f"Closed {closed} signals with outcome")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Signal close commit failed: {e}")
            from app.services.error_tracking import capture
            capture(e, job="close_and_record_signals")


def _claim_watchlist_alert(item, current_price: float, alert_price: float) -> bool:
    """Atomically claim a watchlist price-alert trigger.

    Returns True only if THIS caller transitioned the item out of its
    "armed at this baseline" state, so only one concurrent runner notifies the
    user. Performs the same state change the loop used to do in-session:

      * repeat alerts  -> re-arm by moving alert_set_at_price to the price it
        just fired at, guarded on the baseline still being the old value.
      * one-shot alerts -> disarm by clearing alert_price, guarded on
        alert_price still being set.

    Guarding on the *previous* value is what makes this a claim rather than a
    blind write: a second runner that already lost the race sees rowcount 0.
    """
    from app.models.watchlist import WatchlistItem
    from app.extensions import db

    tbl = WatchlistItem.__table__
    if item.alert_repeat:
        baseline = item.alert_set_at_price
        cond = (tbl.c.alert_set_at_price.is_(None) if baseline is None
                else tbl.c.alert_set_at_price == baseline)
        stmt = tbl.update().where(tbl.c.id == item.id, cond).values(alert_set_at_price=current_price)
    else:
        stmt = tbl.update().where(
            tbl.c.id == item.id, tbl.c.alert_price.isnot(None)
        ).values(alert_price=None)

    result = db.session.execute(stmt)
    db.session.commit()
    return result.rowcount > 0


def _claim_signal_close(signal, new_status: str) -> bool:
    """Atomically transition a signal from "active" to a closed status.

    close_and_record_signals (every 5 min), check_signals_for_price (every
    ~15s via ticker polling, and on every real-time price push from the
    Delta WebSocket stream) and evaluate_expired_predictions can all reach
    the same signal around the same moment. Each of them previously did a
    plain read-then-mutate (`signal.status = outcome`) with no guard, so if
    two of these overlapped, both could see status="active", both compute an
    outcome, and both insert a SignalHistory row for the same signal —
    double-counting one trade in the win-rate/performance stats shown
    throughout the app.

    This performs the status flip as a single conditional UPDATE (`WHERE
    id=... AND status='active'`) and returns True only if a row was actually
    affected — i.e. this call is the one that "won" the race and should
    proceed to write the SignalHistory row. A losing caller sees 0 rows
    affected and skips history entirely, since the winner already recorded it.
    """
    from app.models.signal import Signal
    from app.extensions import db

    result = db.session.execute(
        Signal.__table__.update()
        .where(Signal.id == signal.id, Signal.status == "active")
        .values(status=new_status)
    )
    return result.rowcount > 0


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


def prewarm_ta_cache(app):
    """Pre-compute TA summary and MTF matrix and store in cache so page loads are instant."""
    with app.app_context():
        from app.models.asset import Asset
        from app.services.data.fetcher import market_fetcher, blocked_data_markets
        from app.services.indicators.calculator import calculate_all_indicators
        from app.extensions import cache
        from concurrent.futures import ThreadPoolExecutor
        from app.api.v1.market_data import _compute_ta_rating
        from app.api.v1.signals import _mtf_rating
        from app.services.indicators.ema_mtf import get_ta_timeframes, get_higher_tf_map, compute_ema921_cell

        ta_tfs  = get_ta_timeframes()
        mtf_tfs = ta_tfs
        higher_tf_map = get_higher_tf_map()
        assets  = Asset.query.filter_by(is_active=True).order_by(Asset.market, Asset.symbol).all()

        # Skip markets whose data feed is PAUSED in APIConfig before doing any
        # work. fetch_many() already refuses the paused feed, so those assets
        # would only produce all-None TA/MTF/EMA rows — building and caching
        # them every 5 min is pure waste (CPU + a larger cache payload served
        # to every client). Fetch the blocked set once and filter up front so
        # the whole compute + cache pass skips them entirely.
        blocked = blocked_data_markets()
        if blocked:
            assets = [a for a in assets if a.market not in blocked]

        # Fetch all data once — covers both TA and MTF (union of timeframes)
        all_tfs  = list(dict.fromkeys(ta_tfs + mtf_tfs))  # preserves order, deduplicates
        all_data = market_fetcher.fetch_many(assets, all_tfs, limit=200)

        def _make_ta_and_mtf_rows(asset):
            # ta_tfs == mtf_tfs, and _compute_ta_rating/_mtf_rating both
            # consume the same light=True indicator subset for a given
            # (symbol, tf) — previously computed via two independent calls
            # to calculate_all_indicators (the heaviest step) per cell.
            # Computing it once per tf and feeding both rating functions
            # halves that work across the whole asset x timeframe grid.
            sym = asset.symbol
            dfs = all_data.get(sym, {})
            ta_row = {"id": asset.id, "symbol": sym, "name": asset.name, "market": asset.market,
                      "tf": {}, "price": None, "open": None, "high": None, "low": None,
                      "change": None, "change_pct": None, "volume": None, "time": None}
            df_price = dfs.get("1h")
            if df_price is not None and len(df_price) >= 2:
                try:
                    last  = df_price.iloc[-1]; prev = df_price.iloc[-2]
                    price = float(last["close"]); chg = price - float(prev["close"])
                    ta_row.update({"price": price, "open": float(last["open"]), "high": float(last["high"]),
                                   "low": float(last["low"]), "change": round(chg, 6),
                                   "change_pct": round(chg / float(prev["close"]) * 100, 2) if prev["close"] else 0,
                                   "volume": float(last.get("volume", 0)),
                                   "time": df_price.index[-1].strftime("%H:%M") if hasattr(df_price.index[-1], "strftime") else ""})
                except Exception:
                    pass
            mtf_row = {}
            for tf in ta_tfs:
                df = dfs.get(tf)
                if df is None or len(df) < 52:
                    ta_row["tf"][tf] = None
                    mtf_row[tf] = None
                    continue
                try:
                    ind = calculate_all_indicators(df, light=True)
                    close = float(df["close"].iloc[-1])
                except Exception:
                    ta_row["tf"][tf] = None
                    mtf_row[tf] = None
                    continue
                try:
                    ta_row["tf"][tf] = _compute_ta_rating(ind, close)
                except Exception:
                    ta_row["tf"][tf] = None
                try:
                    mtf_row[tf] = _mtf_rating(ind, close)
                except Exception:
                    mtf_row[tf] = None
            return ta_row, asset.id, mtf_row

        def _make_ema_row(asset):
            sym = asset.symbol
            dfs = all_data.get(sym, {})
            row = {"id": asset.id, "symbol": sym, "name": asset.name, "market": asset.market, "tf": {}}
            read_cache: dict = {}  # shared per-asset across tf columns — see ema_mtf.compute_ema921_cell docstring
            for tf in ta_tfs:
                try:
                    higher_tf = higher_tf_map.get(tf)
                    higher_df = dfs.get(higher_tf) if higher_tf else None
                    row["tf"][tf] = compute_ema921_cell(
                        dfs.get(tf), tf, higher_df, _read_cache=read_cache, _higher_tf_map=higher_tf_map,
                    ).to_dict()
                except Exception:
                    row["tf"][tf] = None
            return row

        # Two workloads (TA+MTF combined, and EMA) only READ the shared
        # all_data (no cross-mutation) and are otherwise fully independent
        # — was three separate `list(ex.map(...))` calls back-to-back, each
        # one blocking (draining the whole pool) before the next started,
        # so the indicator-computation stage took roughly 3x its true
        # wall-clock. Submitting both workloads to one shared pool at once
        # lets them interleave — calculate_all_indicators releases the GIL
        # for its numpy/pandas-heavy operations, so real wall-clock
        # parallelism is available here, not just I/O-bound work.
        with ThreadPoolExecutor(max_workers=8) as ex:
            ta_mtf_futures = [ex.submit(_make_ta_and_mtf_rows, a) for a in assets]
            ema_futures    = [ex.submit(_make_ema_row, a)        for a in assets]
            ta_mtf_results = [f.result() for f in ta_mtf_futures]
            ema_rows       = [f.result() for f in ema_futures]
        ta_rows  = [r[0] for r in ta_mtf_results]
        mtf_rows = [(r[1], r[2]) for r in ta_mtf_results]

        # TTL was 150s, shorter than this job's own 5-min (300s) scheduler
        # interval — leaving a ~2.5 min window where the cache had already
        # expired before the next prewarm refilled it, so any on-demand
        # request landing in that gap paid for a full cold-path
        # recomputation redundantly close to the next scheduled prewarm.
        # Comfortably exceeding the interval keeps the cache always warm
        # from a scheduled prewarm, not from user traffic timing.
        cache.set("ta_summary_all",  {"assets": ta_rows,  "timeframes": ta_tfs},  timeout=330)
        mtf_matrix = {aid: row for aid, row in mtf_rows}
        # mtf_matrix_all and ema_summary_all previously stayed at 150s here
        # even after the ta_summary_all fix above — this job fills all three
        # from the SAME 5-min (300s) scheduler interval, so all three need
        # the same >300s TTL for the same reason.
        cache.set("mtf_matrix_all",  {
            "matrix": mtf_matrix,
            "assets": [{"id": a.id, "symbol": a.symbol, "name": a.name, "market": a.market} for a in assets],
            "timeframes": mtf_tfs,
        }, timeout=330)
        cache.set("ema_summary_all", {"assets": ema_rows, "timeframes": ta_tfs}, timeout=330)
        logger.info("TA/MTF/EMA cache pre-warmed")

        try:
            from app.tasks.notification_tasks import check_rating_changes
            check_rating_changes(app)
        except Exception as e:
            logger.warning(f"Rating-change check failed: {e}")


def prewarm_heatmap(app):
    """Pre-build the Market Heatmap payload so /market-data/heatmap is always a
    cache hit. The heatmap is hit on every dashboard load; without prewarming
    its 180s cache went cold repeatedly and each miss blocked a user request on
    a live fetch. build_heatmap() itself now reads crypto prices from the Delta
    WS cache (instant), so this job is cheap and mainly guarantees the very
    first post-boot load (before the WS populates) doesn't pay the fetch."""
    with app.app_context():
        from app.api.v1.market_data import build_heatmap
        from app.extensions import cache
        try:
            cache.set("market_heatmap", {"heatmap": build_heatmap()}, timeout=210)
            logger.info("Market heatmap cache pre-warmed")
        except Exception as e:
            logger.debug(f"Heatmap prewarm failed: {e}")


def prewarm_ai_cache(app):
    """
    Pre-run AI predictions for all assets × key timeframes every 30 min.
    Stores to the versioned AI summary cache so the Ratings grid is instant.
    Also pre-trains / refreshes joblib model files so inference is fast.
    """
    with app.app_context():
        from app.models.asset import Asset
        from app.models.prediction import Prediction
        from app.services.data.fetcher import market_fetcher, blocked_data_markets
        from app.services.ai.predictor import ai_predictor
        from app.services.ai.prediction_records import build_prediction_record
        from app.services.data.quality import assess_data_quality
        from app.extensions import cache, db
        from datetime import datetime, timedelta

        # Same 5-timeframe compute-cost boundary as ai_summary() in
        # api/v1/market_data.py — each column costs one model inference per
        # asset, so this intentionally stays a subset of the full Platform
        # Config timeframe list even when that list is broader.
        _AI_SUMMARY_SUBSET = ["5m", "15m", "1h", "4h", "1d"]
        from app.services.platform_config import get_display_timeframes
        _configured = [tf for tf in get_display_timeframes() if tf in _AI_SUMMARY_SUBSET]
        tfs    = _configured or _AI_SUMMARY_SUBSET
        assets = Asset.query.filter_by(is_active=True).order_by(Asset.market, Asset.symbol).all()

        # Skip PAUSED-feed markets before fetching/predicting — same rationale
        # as prewarm_ta_cache: fetch_many refuses them, so they'd only yield
        # neutral-default AI cells that get cached and served every 30 min.
        blocked = blocked_data_markets()
        if blocked:
            assets = [a for a in assets if a.market not in blocked]

        # 350, not 220 — see matching comment in api/v1/market_data.py's
        # ai_summary(): 220 raw candles left too few usable rows after
        # feature engineering for some assets, forcing a neutral/50% default.
        all_data = market_fetcher.fetch_many(assets, tfs, limit=350)

        cutoff   = datetime.utcnow() - timedelta(minutes=25)
        asset_ids = [a.id for a in assets]
        recent   = Prediction.query.filter(
            Prediction.asset_id.in_(asset_ids),
            Prediction.timeframe.in_(tfs),
            Prediction.predicted_at >= cutoff,
        ).order_by(Prediction.predicted_at.desc()).all()
        # Newest-first plus setdefault prevents an older row from replacing
        # the latest prediction when multiple rows are inside the cutoff.
        pred_map = {}
        for p in recent:
            pred_map.setdefault((p.asset_id, p.timeframe), p.to_dict())

        def _process(asset):
            row = {"id": asset.id, "symbol": asset.symbol,
                   "name": asset.name, "market": asset.market, "tf": {}}
            for tf in tfs:
                key = (asset.id, tf)
                if key in pred_map:
                    p = pred_map[key]
                    row["tf"][tf] = {
                        "direction":    p["predicted_direction"],
                        "model_version": p.get("model_version"),
                        "data_quality": p.get("data_quality"),
                        "model_outputs": p.get("model_outputs") or {},
                        "confidence":   round(float(p["confidence"]), 1),
                        "bullish_prob": round(float(p["bullish_probability"]), 1),
                        "bearish_prob": round(float(p["bearish_probability"]), 1),
                    }
                    continue
                df = all_data.get(asset.symbol, {}).get(tf)
                try:
                    data_quality = assess_data_quality(df, asset.market, tf)
                    result = ai_predictor.predict(df, asset.symbol, tf)
                    if df is not None and len(df) >= 100 and result.get("model_version"):
                        pred = build_prediction_record(
                            asset_id=asset.id,
                            timeframe=tf,
                            result=result,
                            entry_price=float(df["close"].iloc[-1]),
                            valid_until=datetime.utcnow() + timedelta(hours=4),
                            data_quality=data_quality,
                        )
                        db.session.add(pred)
                    row["tf"][tf] = {
                        "direction":    result["predicted_direction"],
                        "model_version": result.get("model_version"),
                        "data_quality": data_quality,
                        "model_outputs": result.get("model_outputs") or {},
                        "confidence":   round(float(result["confidence"]), 1),
                        "bullish_prob": round(float(result["bullish_probability"]), 1),
                        "bearish_prob": round(float(result["bearish_probability"]), 1),
                    }
                except Exception as e:
                    logger.error(f"AI prewarm failed {asset.symbol}/{tf}: {e}", exc_info=True)
                    row["tf"][tf] = {"direction": "neutral", "model_version": None, "data_quality": None, "model_outputs": {}, "confidence": 50.0,
                                     "bullish_prob": 50.0, "bearish_prob": 50.0}
            return row

        # Sequential, not ThreadPoolExecutor — see matching comment in
        # api/v1/market_data.py's ai_summary(): concurrent .predict_proba()
        # calls against predictor.py's shared cached model objects produced
        # a real, non-deterministic race (same asset correctly predicted on
        # one run, silently fell back to neutral/50% on the next).
        rows = [_process(asset) for asset in assets]

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Matches ta_summary's fix above — was exactly equal to this job's
        # 30-min scheduler interval (no slack at all for scheduler jitter),
        # now comfortably exceeds it.
        cache.set("ai_summary_all:v4", {"assets": rows, "timeframes": tfs}, timeout=1980)
        logger.info(f"AI cache pre-warmed for {len(assets)} assets × {len(tfs)} timeframes")


def evaluate_expired_predictions(app):
    """
    After a prediction's valid_until passes, check if the direction was correct
    by comparing predicted_direction to actual price movement.
    Populates actual_direction, was_correct, evaluated_at on the Prediction row.
    """
    with app.app_context():
        from app.models.prediction import Prediction
        from app.models.asset import Asset
        from app.services.data.fetcher import market_fetcher
        from app.extensions import db, cache
        from datetime import datetime, timedelta

        # Predictions that expired but haven't been evaluated yet
        now = datetime.utcnow()
        unevaluated = Prediction.query.filter(
            Prediction.valid_until <= now,
            Prediction.was_correct == None,
            Prediction.predicted_direction != None,
        ).all()

        if not unevaluated:
            return

        asset_ids = {p.asset_id for p in unevaluated}
        assets_map = {a.id: a for a in Asset.query.filter(Asset.id.in_(asset_ids)).all()}
        price_cache = {}

        for pred in unevaluated:
            try:
                asset = assets_map.get(pred.asset_id)
                if not asset:
                    continue

                # Get current price (1h candle close)
                if asset.id not in price_cache:
                    df = market_fetcher.fetch(asset, "1h", 3)
                    price_cache[asset.id] = float(df["close"].iloc[-1]) if df is not None and not df.empty else None

                current_price = price_cache.get(asset.id)
                if current_price is None:
                    continue

                # Reference price at prediction time: entry_price is the real
                # close price captured when the prediction was made. Older
                # rows created before this field existed fall back to the
                # predicted_target/predicted_stop proxy used previously.
                ref_price = pred.entry_price or pred.predicted_target or pred.predicted_stop
                if not ref_price:
                    # Fallback: compare bullish vs bearish probability shift
                    pred.was_correct = (
                        pred.predicted_direction == "neutral"
                    )
                    pred.actual_direction = "neutral"
                    pred.evaluated_at = now
                    continue

                # Determine actual direction from ref vs current price
                change_pct = (current_price - ref_price) / ref_price * 100
                if change_pct > 0.5:
                    actual = "bullish"
                elif change_pct < -0.5:
                    actual = "bearish"
                else:
                    actual = "neutral"

                pred.actual_direction = actual
                pred.was_correct = (pred.predicted_direction == actual) or (
                    pred.predicted_direction in ("bullish", "bearish") and actual == "neutral"
                )
                pred.evaluated_at = now

            except Exception as e:
                logger.debug(f"Prediction eval failed id={pred.id}: {e}")

        try:
            db.session.commit()
            evaluated = sum(1 for p in unevaluated if p.evaluated_at is not None)
            if evaluated:
                cache.delete("model_perf_stats")
                for pred in unevaluated:
                    if pred.evaluated_at is not None:
                        cache.delete(
                            f"prediction_history_context:{pred.asset_id}:{pred.timeframe}"
                        )
                logger.info(f"Evaluated {evaluated} expired predictions")
        except Exception:
            db.session.rollback()


def check_signals_for_price(symbol: str, price: float, app):
    """
    Real-time TP/SL check triggered by each price update (Binance WS or ticker poll).
    Closes signals immediately when price crosses TP1 or SL — no waiting for the 5-min job.
    Broadcasts signal_closed event via WebSocket.
    """
    with app.app_context():
        # Fast path: most ticks are for symbols with no active signal — skip
        # all DB work for them (this runs on every WS price push).
        if symbol.upper() not in _symbols_with_active_signals():
            return

        from app.models.signal import Signal, SignalHistory
        from app.models.asset import Asset
        from app.extensions import db
        from datetime import datetime

        asset = Asset.query.filter_by(symbol=symbol, is_active=True).first()
        if not asset:
            return

        active = Signal.query.filter_by(asset_id=asset.id, status="active").all()
        if not active:
            return

        closed = []
        now = datetime.utcnow()

        for signal in active:
            try:
                if signal.expires_at and signal.expires_at < now:
                    if _claim_signal_close(signal, "expired"):
                        closed.append(signal)
                    continue

                outcome = _check_outcome(signal, price)
                if not outcome:
                    signal.current_price = price
                    continue

                # Atomically claim the close before writing history — this
                # job fires on every price tick (as often as every few
                # seconds via the Delta WS stream), while the 5-min
                # close_and_record_signals job and the 30-min prediction
                # evaluator can also reach the same signal. Only the caller
                # that actually flips status="active" -> outcome proceeds;
                # a loser (rowcount 0) skips writing a duplicate history row.
                if not _claim_signal_close(signal, outcome):
                    continue

                if signal.signal_type in ("BUY", "HOLD"):
                    pnl_pct = (price - signal.entry_price) / signal.entry_price * 100
                else:
                    pnl_pct = (signal.entry_price - price) / signal.entry_price * 100

                signal.current_price = price
                signal.pnl_pct = round(pnl_pct, 2)

                history_outcome = "win" if outcome == "hit_target" else "loss" if outcome == "hit_sl" else "neutral"
                duration = int((now - signal.generated_at).total_seconds() / 60) if signal.generated_at else None
                db.session.add(SignalHistory(
                    signal_id=signal.id,
                    asset_id=signal.asset_id,
                    timeframe=signal.timeframe,
                    signal_type=signal.signal_type,
                    entry_price=signal.entry_price,
                    exit_price=price,
                    stop_loss=signal.stop_loss,
                    target1=signal.target1,
                    confidence_score=signal.confidence_score,
                    outcome=history_outcome,
                    pnl_pct=round(pnl_pct, 2),
                    duration_minutes=duration,
                    generated_at=signal.generated_at,
                    closed_at=now,
                ))
                closed.append(signal)

            except Exception as e:
                logger.debug(f"RT signal check failed {signal.id}: {e}")

        if closed:
            try:
                db.session.commit()
                for sig in closed:
                    try:
                        from app.websocket.events import broadcast_signal
                        broadcast_signal({**sig.to_dict(), "event": "signal_closed"})
                    except Exception:
                        pass
            except Exception:
                db.session.rollback()


def retrain_stale_models(app):
    """
    Nightly model quality job: delete joblib files older than 24 h so models
    retrain with the latest data on the next prediction call.
    Also clears the in-process prediction cache.
    Runs once per day (wired at 03:00 UTC in register_data_jobs).
    """
    with app.app_context():
        from app.models.asset import Asset
        from app.services.ai.predictor import ai_predictor, _MODEL_DIR
        import time

        tfs = ["5m", "15m", "1h", "4h", "1d"]
        assets = Asset.query.filter_by(is_active=True).all()

        cutoff = time.time() - 86400   # 24 h
        deleted = 0
        for a in assets:
            for tf in tfs:
                try:
                    ai_predictor.force_retrain(a.symbol, tf)
                    deleted += 1
                except Exception as e:
                    logger.debug(f"Retrain clear failed {a.symbol}/{tf}: {e}")

        ai_predictor.invalidate_cache()
        logger.info(f"Model retrain queued for {deleted} symbol/TF combos (will rebuild on next predict call)")


def fetch_news(app):
    """Fetch latest market news from Yahoo Finance RSS (free, no API key)."""
    with app.app_context():
        from app.models.news import News
        from app.models.asset import Asset
        from app.services.news.fetcher import fetch_news_for_symbols
        from app.extensions import db

        assets = Asset.query.filter_by(is_active=True).all()
        symbols = [a.symbol for a in assets]

        try:
            items = fetch_news_for_symbols(symbols)
        except Exception as e:
            logger.error(f"News fetch failed: {e}")
            return

        new_count = 0
        for item in items:
            if not item.get("url"):
                continue
            exists = News.query.filter_by(url=item["url"]).first()
            if exists:
                continue
            news = News(
                title=item["title"],
                summary=item.get("summary"),
                url=item["url"],
                source=item.get("source", "Yahoo Finance"),
                sentiment=item.get("sentiment"),
                sentiment_score=item.get("sentiment_score"),
                related_assets=item.get("related_assets", []),
                published_at=item.get("published_at"),
            )
            db.session.add(news)
            new_count += 1

        try:
            db.session.commit()
            if new_count:
                logger.info(f"Saved {new_count} new news items")
        except Exception as e:
            db.session.rollback()
            logger.error(f"News save failed: {e}")


def fetch_economic_calendar(app):
    """Fetch economic calendar from Forex Factory free JSON API."""
    with app.app_context():
        from app.models.economic import EconomicEvent
        from app.extensions import db, cache
        import requests
        from datetime import datetime, timezone

        urls = [
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
        ]
        all_events = []
        for url in urls:
            try:
                resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                all_events.extend(resp.json())
            except Exception as e:
                logger.debug(f"Economic calendar fetch failed for {url}: {e}")

        # Parse every event first (pure computation, no DB) so the existing
        # rows can be batch-fetched in ONE query instead of one
        # EconomicEvent.query.filter_by(title=..., event_time=...) SELECT per
        # event — this job pulls ~200-400 events per run (two ForexFactory
        # weeks), so that was 200-400 round trips every 6h for what a single
        # ranged query covers.
        parsed = []
        for ev in all_events:
            title = ev.get("title", "").strip()
            date_str = ev.get("date", "")
            if not title or not date_str:
                continue
            # Parse ISO date string (e.g. "2024-01-15T13:30:00-05:00"). Forex
            # Factory sends the event's own timezone offset (US Eastern) — it
            # must be converted to UTC, not discarded, or every event lands
            # 4-5 hours early (the bug this replaces). Naive datetimes are
            # stored as UTC everywhere else in this app (datetime.utcnow()),
            # so we normalize to that convention here too.
            event_time = None
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = datetime.strptime(date_str, fmt)
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                    event_time = dt
                    break
                except ValueError:
                    continue
            if not event_time:
                continue

            impact_raw = (ev.get("impact") or "").lower()
            impact = impact_raw if impact_raw in ("high", "medium", "low") else "low"
            country = ev.get("country", "")
            parsed.append({
                "title": title, "event_time": event_time, "impact": impact,
                "country": country, "forecast": ev.get("forecast"),
                "previous": ev.get("previous"), "actual": ev.get("actual"),
            })

        saved = 0
        if parsed:
            times = [p["event_time"] for p in parsed]
            existing_rows = (
                EconomicEvent.query
                .filter(EconomicEvent.event_time.between(min(times), max(times)))
                .all()
            )
            existing_by_key = {(e.title, e.event_time): e for e in existing_rows}

            for p in parsed:
                key = (p["title"], p["event_time"])
                existing = existing_by_key.get(key)
                if existing:
                    existing.actual = p["actual"] or existing.actual
                    existing.forecast = p["forecast"] or existing.forecast
                    existing.previous = p["previous"] or existing.previous
                else:
                    event = EconomicEvent(
                        title=p["title"],
                        country=p["country"],
                        currency=p["country"],  # FF uses currency code as country
                        impact=p["impact"],
                        forecast=p["forecast"],
                        previous=p["previous"],
                        actual=p["actual"],
                        event_time=p["event_time"],
                    )
                    db.session.add(event)
                    # The two overlapping ForexFactory week-URLs can return the
                    # same event twice in one run. Record it in the lookup
                    # immediately so a duplicate later in THIS SAME batch
                    # updates this in-memory row instead of inserting a
                    # second one — existing_by_key was only seeded from the
                    # DB once, before the loop, so without this a repeat key
                    # would never be seen as "existing" and would insert twice.
                    existing_by_key[key] = event
                    saved += 1

        try:
            db.session.commit()
            # Invalidate cache so next request re-fetches from DB
            cache.delete("econ_calendar")
            if saved:
                logger.info(f"Saved {saved} new economic events")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Economic calendar save failed: {e}")


def check_watchlist_alerts(app):
    """Check if any watchlist items have crossed their alert price and notify the user."""
    with app.app_context():
        from app.models.watchlist import WatchlistItem, Watchlist
        from app.models.notification import Notification
        from app.models.asset import Asset
        from app.models.user import User
        from app.services.data.fetcher import market_fetcher
        from app.extensions import db
        from app.services.platform_config import get_platform_config
        from app.tasks.notification_tasks import _market_enabled

        _tg_cfg = get_platform_config()

        # joinedload(asset): the loop below reads item.asset for every item, so
        # without eager loading this fired one extra SELECT per watchlist item
        # on a job that runs every 2 minutes across ALL users' watchlists. The
        # watchlist->user lookups below were already batched for exactly this
        # reason; the asset relationship had been missed.
        from sqlalchemy.orm import joinedload
        items = (WatchlistItem.query
                 .options(joinedload(WatchlistItem.asset))
                 .filter(WatchlistItem.alert_price.isnot(None))
                 .all())
        if not items:
            return

        # Build asset cache to avoid duplicate fetches
        price_cache = {}
        # Watchlist -> owning user, batched up front to avoid a query per
        # crossing (previously Watchlist.query.get(item.watchlist_id) ran
        # once per triggered item inside the loop).
        wl_ids = {i.watchlist_id for i in items}
        watchlists_map = {w.id: w for w in Watchlist.query.filter(Watchlist.id.in_(wl_ids)).all()}
        user_ids = {w.user_id for w in watchlists_map.values()}
        users_map = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()}
        triggered = 0

        for item in items:
            try:
                asset = item.asset
                if not asset:
                    continue

                # Fetch current price (cached per asset id)
                if asset.id not in price_cache:
                    ticker = market_fetcher.fetch_ticker(asset)
                    if ticker and ticker.get("price"):
                        price_cache[asset.id] = float(ticker["price"])
                    else:
                        price_cache[asset.id] = None

                current_price = price_cache.get(asset.id)
                if current_price is None:
                    continue

                alert_price = float(item.alert_price)
                symbol = asset.symbol

                # Fire only on an actual *crossing*: the price must have
                # started on one side of alert_price (at alert_set_at_price)
                # and now be on the other side. Without this, comparing
                # current_price against alert_price alone is a tautology
                # (current_price is always either >= or <= alert_price) and
                # every alert fired immediately on the very next poll,
                # regardless of direction. Legacy rows with no
                # alert_set_at_price recorded fall back to firing once the
                # price is observed on either side, same as before.
                if item.alert_set_at_price is not None:
                    started_below = item.alert_set_at_price < alert_price
                    crossed = (
                        (started_below and current_price >= alert_price) or
                        (not started_below and current_price <= alert_price)
                    )
                else:
                    crossed = current_price >= alert_price or current_price <= alert_price

                if crossed:
                    # Determine the watchlist owner
                    watchlist = watchlists_map.get(item.watchlist_id)
                    if not watchlist:
                        continue
                    user_id = watchlist.user_id
                    user = users_map.get(user_id)

                    # Claim the trigger BEFORE notifying. This loop used to
                    # send Telegram/push/WebSocket and only mutate the item's
                    # alert state in-session, committing at the very end — so
                    # two overlapping runs of this job (guaranteed the moment
                    # more than one process registers it) could both observe
                    # the same un-fired alert and both notify the user. Same
                    # conditional-UPDATE approach as _claim_signal_close.
                    if not _claim_watchlist_alert(item, current_price, alert_price):
                        continue

                    direction = "above" if current_price >= alert_price else "below"
                    title = f"{symbol} hit your alert price"
                    msg = (
                        f"{symbol} crossed ₹{alert_price:.2f} — "
                        f"current price: ₹{current_price:.2f} ({direction} alert)"
                    )
                    notif = Notification(
                        user_id=user_id,
                        title=title,
                        message=msg,
                        notification_type="price_alert",
                        channel="web",
                        asset_symbol=symbol,
                    )
                    db.session.add(notif)

                    # The re-arm (repeat) / disarm (one-shot) state change is
                    # performed atomically by _claim_watchlist_alert above —
                    # doing it here as well would be redundant and would
                    # re-open the race it closes.
                    triggered += 1

                    # Broadcast via WebSocket if available
                    try:
                        from app.websocket.events import broadcast_notification
                        broadcast_notification(user_id, title, msg)
                    except Exception:
                        pass  # WebSocket broadcast is best-effort

                    # Previously web/WebSocket only — signal alerts
                    # (fire_signal_alerts) already deliver via
                    # Telegram/push too, but watchlist price alerts never
                    # did, so a user relying on Telegram/push for signal
                    # alerts got silently weaker coverage for their own
                    # manually-set watchlist alerts.
                    if (user and user.telegram_enabled and user.telegram_chat_id
                            and _market_enabled(_tg_cfg, "telegram_watchlist_individual_markets", asset.market)):
                        try:
                            from app.tasks.notification_tasks import _send_telegram, _TELEGRAM_DISCLAIMER
                            arrow = "📈" if direction == "above" else "📉"
                            tg_text = (
                                f"🔔 *WATCHLIST ALERT — {symbol}*\n\n"
                                f"{arrow} Crossed `₹{alert_price:.2f}` ({direction})\n"
                                f"Current price: `₹{current_price:.2f}`"
                            ) + _TELEGRAM_DISCLAIMER
                            _send_telegram(user, tg_text)
                        except Exception:
                            pass
                    if user and user.push_enabled and user.push_subscription:
                        try:
                            from app.services.push import send_push_to_user
                            send_push_to_user(user, title, msg, url="/watchlist")
                        except Exception:
                            pass

            except Exception as e:
                logger.debug(f"Watchlist alert check failed for item {item.id}: {e}")

        try:
            db.session.commit()
            if triggered:
                logger.info(f"Fired {triggered} watchlist price alerts")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Watchlist alert commit failed: {e}")


def nightly_cleanup(app):
    """
    Automated maintenance: purge stale data to keep the database lean.
    Runs daily at 02:00 UTC. Retention policy:
      - System / audit logs  : 7 days
      - News articles        : 7 days
      - Economic events      : 7 days (past events)
      - Notifications (sent) : 7 days
      - Signal history       : 60 days
      - Expired signals      : 30 days
    """
    with app.app_context():
        from app.models.audit import AuditLog, SystemLog
        from app.models.news import News
        from app.models.economic import EconomicEvent
        from app.models.notification import Notification
        from app.models.signal import Signal, SignalHistory
        from app.models.api_config import APILog
        from app.extensions import db
        from datetime import datetime, timedelta

        now        = datetime.utcnow()
        week_ago   = now - timedelta(days=7)
        month_ago  = now - timedelta(days=30)
        two_months = now - timedelta(days=60)
        # Audit logs (security/compliance trail: logins, signups, admin
        # actions, account deletions) need to outlive routine system/debug
        # logs by a lot — incident investigations and abuse reports often
        # come in well after a week. System logs stay at 7 days (pure
        # operational noise); audit logs get a full year.
        audit_retention = now - timedelta(days=365)

        stats = {}
        try:
            # 1. System logs older than 7 days
            n = SystemLog.query.filter(SystemLog.created_at < week_ago).delete()
            stats["system_logs"] = n

            # 2. Audit logs older than 1 year
            n = AuditLog.query.filter(AuditLog.created_at < audit_retention).delete()
            stats["audit_logs"] = n

            # 3. Old news articles
            n = News.query.filter(News.published_at < week_ago).delete()
            stats["news"] = n

            # 4. Past economic events older than 7 days
            n = EconomicEvent.query.filter(EconomicEvent.event_time < week_ago).delete()
            stats["economic_events"] = n

            # 5. Sent notifications older than 7 days
            n = Notification.query.filter(
                Notification.created_at < week_ago,
                Notification.is_sent == True,
            ).delete()
            stats["notifications"] = n

            # 6. Signal history older than 60 days
            n = SignalHistory.query.filter(SignalHistory.closed_at < two_months).delete()
            stats["signal_history"] = n

            # 7. Old expired/closed signals (keep active ones indefinitely)
            n = Signal.query.filter(
                Signal.status.in_(["expired", "hit_target", "hit_sl"]),
                Signal.generated_at < month_ago,
            ).delete(synchronize_session=False)
            stats["old_signals"] = n

            # 8. API logs older than 7 days
            n = APILog.query.filter(APILog.created_at < week_ago).delete()
            stats["api_logs"] = n

            db.session.commit()

            total = sum(stats.values())
            logger.info(f"Nightly cleanup: removed {total} rows — {stats}")

        except Exception as e:
            db.session.rollback()
            logger.error(f"Nightly cleanup failed: {e}")


def expire_live_read_logs(app):
    """Close stale Terminal preview reads as neutral outcomes.

    Live-read cards are intentionally measured against target3, so a read can
    remain open after reaching target1. Once its timeframe window ends it must
    become an explicit neutral result instead of disappearing from the win-rate
    denominator when the Redis card cache expires.
    """
    with app.app_context():
        from app.models.live_read_log import LiveReadLog
        from app.extensions import cache, db
        from datetime import datetime

        now = datetime.utcnow()
        try:
            expired = (
                LiveReadLog.query
                .filter(
                    LiveReadLog.outcome.is_(None),
                    LiveReadLog.expires_at.isnot(None),
                    LiveReadLog.expires_at <= now,
                )
                .update(
                    {
                        LiveReadLog.outcome: "expired",
                        LiveReadLog.resolved_at: now,
                    },
                    synchronize_session=False,
                )
            )
            if expired:
                db.session.commit()
                cache.delete("signals_live_read_performance")
                logger.info("Marked %d stale Terminal live reads as expired.", expired)
            else:
                db.session.rollback()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Live-read expiry cleanup failed: {e}")


def prewarm_delta_market_screener(app):
    """Pre-compute the flexible-condition screener's metric universe (price,
    24h change, volume, RSI(14), funding, open interest) for each asset type,
    so every filter combination a user tries is served from cache instead of
    recomputing RSI for ~220 contracts on the first request after it expires."""
    with app.app_context():
        from app.api.v1.scanner import get_delta_screener_universe
        from app.services.scanner.delta_market_screener import ASSET_TYPES

        for asset_type in ASSET_TYPES:
            try:
                get_delta_screener_universe(asset_type)
            except Exception:
                logger.exception("Delta market screener prewarm failed for %s", asset_type)


def prewarm_delta_indicator_screener(app):
    """Pre-compute the indicator-crossover screener's per-symbol OHLCV +
    indicator universe for perpetual_futures (the ~220-contract asset type)
    across all three candle timeframes. Spot/move_options are only ~4
    contracts each — cheap enough to compute on first request rather than
    reserving scheduler time for them."""
    with app.app_context():
        from app.api.v1.scanner import get_delta_indicator_universe
        from app.services.scanner.delta_indicator_scanner import TIMEFRAMES

        for timeframe in TIMEFRAMES:
            try:
                get_delta_indicator_universe("perpetual_futures", timeframe)
            except Exception:
                logger.exception("Delta indicator screener prewarm failed for %s", timeframe)


def prewarm_delta_scanner(app):
    """Pre-compute the Delta Exchange multi-timeframe EMA+Supertrend scan and
    store it in cache so /delta-scanner page loads are instant instead of
    waiting on a ~100-contract-wide live scan (see api/v1/scanner.py)."""
    with app.app_context():
        from app.extensions import cache
        from app.services.scanner.delta_mtf_scanner import run_scan
        from app.api.v1.scanner import DELTA_SCANNER_CACHE_KEY

        try:
            result = run_scan()
            cache.set(DELTA_SCANNER_CACHE_KEY, result, timeout=330)
        except Exception:
            logger.exception("Delta MTF scanner prewarm failed")


def register_data_jobs(scheduler, app):
    # Non-crypto ticker fallback — every 15 seconds (crypto handled by Binance WS stream)
    scheduler.add_job(update_tickers, "interval", seconds=15,
                      args=[app], id="update_tickers", replace_existing=True)
    # Signal outcome tracking — every 5 minutes
    scheduler.add_job(close_and_record_signals, "interval", minutes=5,
                      args=[app], id="close_signals", replace_existing=True)
    # TA/MTF cache pre-warm — every 5 minutes
    scheduler.add_job(prewarm_ta_cache, "interval", minutes=5,
                      args=[app], id="prewarm_ta", replace_existing=True)
    # Market heatmap pre-warm — every 3 minutes (matches the frontend's 180s
    # refresh) so /market-data/heatmap is always served from a warm cache.
    scheduler.add_job(prewarm_heatmap, "interval", minutes=3,
                      args=[app], id="prewarm_heatmap", replace_existing=True)
    # Delta Exchange MTF scanner pre-warm — every 5 minutes (cache TTL 330s)
    scheduler.add_job(prewarm_delta_scanner, "interval", minutes=5,
                      args=[app], id="prewarm_delta_scanner", replace_existing=True)
    # Delta market screener universe pre-warm — every 2 minutes (cache TTL 120s)
    scheduler.add_job(prewarm_delta_market_screener, "interval", minutes=2,
                      args=[app], id="prewarm_delta_screener", replace_existing=True)
    # Delta indicator-crossover screener pre-warm — every 3 minutes (cache TTL 180s),
    # perpetual_futures across all 3 candle timeframes (~5-8s each).
    scheduler.add_job(prewarm_delta_indicator_screener, "interval", minutes=3,
                      args=[app], id="prewarm_delta_indicator_screener", replace_existing=True)
    # AI predictions pre-warm — every 30 minutes
    scheduler.add_job(prewarm_ai_cache, "interval", minutes=30,
                      args=[app], id="prewarm_ai", replace_existing=True)
    # News feed — every 30 minutes
    scheduler.add_job(fetch_news, "interval", minutes=30,
                      args=[app], id="fetch_news", replace_existing=True)
    # Economic calendar — every 6 hours
    scheduler.add_job(fetch_economic_calendar, "interval", hours=6,
                      args=[app], id="fetch_econ_calendar", replace_existing=True)
    # Watchlist price alerts — every 2 minutes
    scheduler.add_job(check_watchlist_alerts, "interval", minutes=2,
                      args=[app], id="watchlist_alerts", replace_existing=True)
    # Prediction accuracy evaluation — every 30 minutes
    scheduler.add_job(evaluate_expired_predictions, "interval", minutes=30,
                      args=[app], id="eval_predictions", replace_existing=True)
    # Terminal preview expiry — every 5 minutes, aligned with signal outcome
    # tracking so stale reads become explicit neutral results promptly.
    scheduler.add_job(expire_live_read_logs, "interval", minutes=5,
                      args=[app], id="expire_live_read_logs", replace_existing=True)
    # Nightly database cleanup — runs at 02:00 UTC every day
    scheduler.add_job(nightly_cleanup, "cron", hour=2, minute=0,
                      args=[app], id="nightly_cleanup", replace_existing=True)
    # Nightly model retrain (clears stale joblib files) — 03:00 UTC
    scheduler.add_job(retrain_stale_models, "cron", hour=3, minute=0,
                      args=[app], id="retrain_models", replace_existing=True)

    # ── Startup pre-warm: run TA + AI shortly after boot ─────────
    from datetime import datetime, timedelta
    scheduler.add_job(prewarm_ta_cache, "date",
                      run_date=datetime.utcnow() + timedelta(seconds=15),
                      args=[app], id="prewarm_ta_startup",
                      replace_existing=True, misfire_grace_time=60)
    scheduler.add_job(prewarm_ai_cache, "date",
                      run_date=datetime.utcnow() + timedelta(seconds=30),
                      args=[app], id="prewarm_ai_startup",
                      replace_existing=True, misfire_grace_time=120)
    scheduler.add_job(prewarm_heatmap, "date",
                      run_date=datetime.utcnow() + timedelta(seconds=20),
                      args=[app], id="prewarm_heatmap_startup",
                      replace_existing=True, misfire_grace_time=60)
    scheduler.add_job(prewarm_delta_scanner, "date",
                      run_date=datetime.utcnow() + timedelta(seconds=25),
                      args=[app], id="prewarm_delta_scanner_startup",
                      replace_existing=True, misfire_grace_time=120)
    scheduler.add_job(prewarm_delta_market_screener, "date",
                      run_date=datetime.utcnow() + timedelta(seconds=35),
                      args=[app], id="prewarm_delta_screener_startup",
                      replace_existing=True, misfire_grace_time=120)
    scheduler.add_job(prewarm_delta_indicator_screener, "date",
                      run_date=datetime.utcnow() + timedelta(seconds=45),
                      args=[app], id="prewarm_delta_indicator_screener_startup",
                      replace_existing=True, misfire_grace_time=120)

    logger.info("Data jobs registered (TA + heatmap + AI startup pre-warm queued)")
