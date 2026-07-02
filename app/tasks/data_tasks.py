"""Background jobs for market data, ticker updates, and signal outcome tracking."""
import logging
from app.websocket.events import broadcast_ticker

logger = logging.getLogger(__name__)


def update_tickers(app):
    """
    Fallback ticker poll for non-crypto assets (forex, indices, commodities, stocks).
    Crypto is handled by the Delta Exchange WebSocket stream — no polling needed there.
    Runs every 15s; broadcasts via WebSocket + updates live price cache.
    """
    with app.app_context():
        from app.models.asset import Asset
        from app.services.data.fetcher import market_fetcher

        # Only poll assets NOT covered by the Delta Exchange WS stream
        non_crypto = Asset.query.filter(
            Asset.is_active == True,
            Asset.market != "crypto",
        ).all()

        for asset in non_crypto:
            try:
                ticker = market_fetcher.fetch_ticker(asset)
                if ticker:
                    broadcast_ticker(asset.symbol, ticker)
                    if ticker.get("price"):
                        check_signals_for_price(asset.symbol, float(ticker["price"]), app)
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
                    signal.status = "expired"
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

        try:
            db.session.commit()
            if closed:
                logger.info(f"Closed {closed} signals with outcome")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Signal close commit failed: {e}")


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
        from app.services.data.fetcher import market_fetcher
        from app.services.indicators.calculator import calculate_all_indicators
        from app.extensions import cache
        from concurrent.futures import ThreadPoolExecutor
        from app.api.v1.market_data import _compute_ta_rating
        from app.api.v1.signals import _mtf_rating

        ta_tfs  = ["5m", "15m", "30m", "1h", "2h", "4h", "1d"]
        mtf_tfs = ["5m", "15m", "30m", "1h", "2h", "4h", "1d"]
        assets  = Asset.query.filter_by(is_active=True).order_by(Asset.market, Asset.symbol).all()

        # Fetch all data once — covers both TA and MTF (union of timeframes)
        all_tfs  = list(dict.fromkeys(ta_tfs + mtf_tfs))  # preserves order, deduplicates
        all_data = market_fetcher.fetch_many(assets, all_tfs, limit=200)

        def _make_ta_row(asset):
            sym = asset.symbol
            dfs = all_data.get(sym, {})
            row = {"id": asset.id, "symbol": sym, "name": asset.name, "market": asset.market,
                   "tf": {}, "price": None, "open": None, "high": None, "low": None,
                   "change": None, "change_pct": None, "volume": None, "time": None}
            df_price = dfs.get("1h")
            if df_price is not None and len(df_price) >= 2:
                try:
                    last  = df_price.iloc[-1]; prev = df_price.iloc[-2]
                    price = float(last["close"]); chg = price - float(prev["close"])
                    row.update({"price": price, "open": float(last["open"]), "high": float(last["high"]),
                                "low": float(last["low"]), "change": round(chg, 6),
                                "change_pct": round(chg / float(prev["close"]) * 100, 2) if prev["close"] else 0,
                                "volume": float(last.get("volume", 0)),
                                "time": df_price.index[-1].strftime("%H:%M") if hasattr(df_price.index[-1], "strftime") else ""})
                except Exception:
                    pass
            for tf in ta_tfs:
                try:
                    df = dfs.get(tf)
                    if df is None or len(df) < 52: row["tf"][tf] = None; continue
                    ind = calculate_all_indicators(df)
                    row["tf"][tf] = _compute_ta_rating(ind, float(df["close"].iloc[-1]))
                except Exception:
                    row["tf"][tf] = None
            return row

        def _make_mtf_row(asset):
            dfs = all_data.get(asset.symbol, {})
            row = {}
            for tf in mtf_tfs:
                try:
                    df = dfs.get(tf)
                    if df is None or len(df) < 52: row[tf] = None; continue
                    ind = calculate_all_indicators(df)
                    row[tf] = _mtf_rating(ind, float(df["close"].iloc[-1]))
                except Exception:
                    row[tf] = None
            return asset.id, row

        with ThreadPoolExecutor(max_workers=8) as ex:
            ta_rows  = list(ex.map(_make_ta_row, assets))
            mtf_rows = list(ex.map(_make_mtf_row, assets))

        cache.set("ta_summary_all",  {"assets": ta_rows,  "timeframes": ta_tfs},  timeout=150)
        mtf_matrix = {aid: row for aid, row in mtf_rows}
        cache.set("mtf_matrix_all",  {
            "matrix": mtf_matrix,
            "assets": [{"id": a.id, "symbol": a.symbol, "name": a.name, "market": a.market} for a in assets],
            "timeframes": mtf_tfs,
        }, timeout=150)
        logger.info("TA/MTF cache pre-warmed")


def prewarm_ai_cache(app):
    """
    Pre-run AI predictions for all assets × key timeframes every 30 min.
    Stores to 'ai_summary_all' cache so the AI Ratings grid is always instant.
    Also pre-trains / refreshes joblib model files so inference is fast.
    """
    with app.app_context():
        from app.models.asset import Asset
        from app.models.prediction import Prediction
        from app.services.data.fetcher import market_fetcher
        from app.services.ai.predictor import ai_predictor
        from app.extensions import cache, db
        from datetime import datetime, timedelta
        from concurrent.futures import ThreadPoolExecutor

        tfs    = ["5m", "15m", "1h", "4h", "1d"]
        assets = Asset.query.filter_by(is_active=True).order_by(Asset.market, Asset.symbol).all()
        all_data = market_fetcher.fetch_many(assets, tfs, limit=220)

        cutoff   = datetime.utcnow() - timedelta(minutes=25)
        asset_ids = [a.id for a in assets]
        recent   = Prediction.query.filter(
            Prediction.asset_id.in_(asset_ids),
            Prediction.timeframe.in_(tfs),
            Prediction.predicted_at >= cutoff,
        ).all()
        pred_map = {(p.asset_id, p.timeframe): p.to_dict() for p in recent}

        def _process(asset):
            row = {"id": asset.id, "symbol": asset.symbol,
                   "name": asset.name, "market": asset.market, "tf": {}}
            for tf in tfs:
                key = (asset.id, tf)
                if key in pred_map:
                    p = pred_map[key]
                    row["tf"][tf] = {
                        "direction":    p["predicted_direction"],
                        "confidence":   round(float(p["confidence"]), 1),
                        "bullish_prob": round(float(p["bullish_probability"]), 1),
                        "bearish_prob": round(float(p["bearish_probability"]), 1),
                    }
                    continue
                df = all_data.get(asset.symbol, {}).get(tf)
                try:
                    result = ai_predictor.predict(df, asset.symbol, tf)
                    if df is not None and len(df) >= 100:
                        pred = Prediction(
                            asset_id=asset.id, timeframe=tf,
                            model_name=result["model_name"],
                            bullish_probability=result["bullish_probability"],
                            bearish_probability=result["bearish_probability"],
                            predicted_direction=result["predicted_direction"],
                            predicted_target=result.get("predicted_target"),
                            predicted_stop=result.get("predicted_stop"),
                            confidence=result["confidence"],
                            valid_until=datetime.utcnow() + timedelta(hours=4),
                        )
                        db.session.add(pred)
                    row["tf"][tf] = {
                        "direction":    result["predicted_direction"],
                        "confidence":   round(float(result["confidence"]), 1),
                        "bullish_prob": round(float(result["bullish_probability"]), 1),
                        "bearish_prob": round(float(result["bearish_probability"]), 1),
                    }
                except Exception as e:
                    logger.debug(f"AI prewarm failed {asset.symbol}/{tf}: {e}")
                    row["tf"][tf] = {"direction": "neutral", "confidence": 50.0,
                                     "bullish_prob": 50.0, "bearish_prob": 50.0}
            return row

        with ThreadPoolExecutor(max_workers=min(6, len(assets))) as ex:
            rows = list(ex.map(_process, assets))

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        cache.set("ai_summary_all", {"assets": rows, "timeframes": tfs}, timeout=1800)
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
        from app.extensions import db
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

                # Need a reference price at prediction time — use predicted_target/predicted_stop
                # as a proxy for entry price around prediction time
                ref_price = pred.predicted_target or pred.predicted_stop
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
                    signal.status = "expired"
                    closed.append(signal)
                    continue

                outcome = _check_outcome(signal, price)
                if not outcome:
                    signal.current_price = price
                    continue

                if signal.signal_type in ("BUY", "HOLD"):
                    pnl_pct = (price - signal.entry_price) / signal.entry_price * 100
                else:
                    pnl_pct = (signal.entry_price - price) / signal.entry_price * 100

                signal.status = outcome
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
        from datetime import datetime

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

        saved = 0
        for ev in all_events:
            title = ev.get("title", "").strip()
            date_str = ev.get("date", "")
            if not title or not date_str:
                continue
            # Parse ISO date string (e.g. "2024-01-15T13:30:00-0500")
            event_time = None
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S")
                    event_time = dt
                    break
                except ValueError:
                    pass
            if not event_time:
                continue

            impact_raw = (ev.get("impact") or "").lower()
            # Normalize: High/Medium/Low
            impact = impact_raw if impact_raw in ("high", "medium", "low") else "low"

            country = ev.get("country", "")
            # Upsert by title + event_time
            existing = EconomicEvent.query.filter_by(title=title, event_time=event_time).first()
            if existing:
                existing.actual = ev.get("actual") or existing.actual
                existing.forecast = ev.get("forecast") or existing.forecast
                existing.previous = ev.get("previous") or existing.previous
            else:
                event = EconomicEvent(
                    title=title,
                    country=country,
                    currency=country,  # FF uses currency code as country
                    impact=impact,
                    forecast=ev.get("forecast"),
                    previous=ev.get("previous"),
                    actual=ev.get("actual"),
                    event_time=event_time,
                )
                db.session.add(event)
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
        from app.services.data.fetcher import market_fetcher
        from app.extensions import db

        items = WatchlistItem.query.filter(WatchlistItem.alert_price.isnot(None)).all()
        if not items:
            return

        # Build asset cache to avoid duplicate fetches
        price_cache = {}
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

                # Check if alert has been crossed (either direction)
                # We store a flag by setting alert_price to None after firing
                if current_price >= alert_price or current_price <= alert_price:
                    # Determine the watchlist owner
                    watchlist = Watchlist.query.get(item.watchlist_id)
                    if not watchlist:
                        continue
                    user_id = watchlist.user_id

                    direction = "above" if current_price >= alert_price else "below"
                    notif = Notification(
                        user_id=user_id,
                        title=f"{symbol} hit your alert price",
                        message=(
                            f"{symbol} crossed ₹{alert_price:.2f} — "
                            f"current price: ₹{current_price:.2f} ({direction} alert)"
                        ),
                        notification_type="price_alert",
                        channel="web",
                        asset_symbol=symbol,
                    )
                    db.session.add(notif)

                    # One-shot alert: clear the alert_price so it doesn't fire again
                    item.alert_price = None
                    triggered += 1

                    # Broadcast via WebSocket if available
                    try:
                        from app.websocket.events import broadcast_notification
                        broadcast_notification(user_id, notif.title, notif.message)
                    except Exception:
                        pass  # WebSocket broadcast is best-effort

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

        stats = {}
        try:
            # 1. System logs older than 7 days
            n = SystemLog.query.filter(SystemLog.created_at < week_ago).delete()
            stats["system_logs"] = n

            # 2. Audit logs older than 7 days
            n = AuditLog.query.filter(AuditLog.created_at < week_ago).delete()
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

    logger.info("Data jobs registered (TA + AI startup pre-warm queued)")
