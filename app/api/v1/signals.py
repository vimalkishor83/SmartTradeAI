from flask import Blueprint, request, jsonify, current_app, Response
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from app.models.signal import Signal, SignalHistory
from app.models.asset import Asset
from app.models.user import User
from app.extensions import db, cache
from app.auth.decorators import login_required
from app.services.signals.engine import signal_engine
from app.services.data.fetcher import market_fetcher
from app.services.sentiment.engine import calculate_sentiment
from datetime import datetime, timedelta
from sqlalchemy import and_, func
import logging
import csv
import io

logger = logging.getLogger(__name__)

signals_bp = Blueprint("signals", __name__)

# ── Server-side Auto Generate state ──────────────────────────────────────────
_AG_STATE = {
    "running": False,
    "market": "crypto",
    "timeframe": "1h",
    "signal_filter": "all",
    "min_confidence": 0,
    "max_per_run": 0,
    "interval_minutes": 5,
    "runs": 0,
    "generated": 0,
    "errors": 0,
    "buy": 0,
    "sell": 0,
    "hold": 0,
    "last_run_at": None,
    "next_run_at": None,
    "log": [],
}
_AG_JOB_ID = "user_auto_generate"


def _ag_log(msg):
    _AG_STATE["log"].append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")
    if len(_AG_STATE["log"]) > 100:
        _AG_STATE["log"] = _AG_STATE["log"][-100:]


def _run_auto_generate(app):
    with app.app_context():
        market    = _AG_STATE["market"]
        timeframe = _AG_STATE["timeframe"]
        sig_filter = _AG_STATE["signal_filter"]
        min_conf  = _AG_STATE["min_confidence"]
        max_per   = _AG_STATE["max_per_run"]

        query = Asset.query.filter_by(is_active=True)
        if market and market != "all":
            query = query.filter_by(market=market)
        assets = query.all()

        _AG_STATE["runs"] += 1
        _AG_STATE["last_run_at"] = datetime.utcnow().isoformat()
        interval = _AG_STATE["interval_minutes"]
        _AG_STATE["next_run_at"] = (
            datetime.utcnow() + timedelta(minutes=interval)
        ).isoformat() if interval > 0 else None

        _ag_log(f"▶ Run #{_AG_STATE['runs']} — {market}/{timeframe} — {len(assets)} assets")
        count = 0

        for asset in assets:
            if max_per and count >= max_per:
                break
            try:
                df = market_fetcher.fetch(asset, timeframe, 300)
                if df is None:
                    continue

                result = signal_engine.generate_signal(df, asset, timeframe)
                if not result:
                    continue

                stype = result["signal_type"]

                # Apply signal filter
                if sig_filter == "buy_sell" and stype not in ("BUY", "SELL"):
                    continue
                if sig_filter == "buy" and stype != "BUY":
                    continue
                if sig_filter == "sell" and stype != "SELL":
                    continue
                if sig_filter == "strong" and result.get("confidence_score", 0) < 70:
                    continue
                if result.get("confidence_score", 0) < min_conf:
                    continue

                # Skip if same asset already has a recent active signal (< 30 min)
                cutoff = datetime.utcnow() - timedelta(minutes=30)
                recent = Signal.query.filter(and_(
                    Signal.asset_id == asset.id,
                    Signal.timeframe == timeframe,
                    Signal.status == "active",
                    Signal.generated_at >= cutoff,
                )).first()
                if recent:
                    _ag_log(f"  ↷ {asset.symbol} skipped — active signal from {int((datetime.utcnow() - recent.generated_at).total_seconds() / 60)}m ago")
                    continue

                sig = Signal(
                    asset_id=asset.id,
                    timeframe=timeframe,
                    **{k: v for k, v in result.items()
                       if k in ["signal_type","entry_price","stop_loss","target1","target2","target3",
                                "risk_reward","confidence_score","confidence_label","trend_score",
                                "momentum_score","volume_score","pattern_score","ai_score",
                                "indicators","patterns","reasoning","expires_at"]},
                )
                db.session.add(sig)
                db.session.flush()

                _AG_STATE["generated"] += 1
                if stype == "BUY":   _AG_STATE["buy"]  += 1
                elif stype == "SELL": _AG_STATE["sell"] += 1
                else:                 _AG_STATE["hold"] += 1
                count += 1
                _ag_log(f"  ✓ {asset.symbol} → {stype} {result.get('confidence_score',0):.0f}%")

            except Exception as e:
                _AG_STATE["errors"] += 1
                _ag_log(f"  ✗ {asset.symbol}: {e}")

        try:
            db.session.commit()
            _ag_log(f"✔ Done — {count} signals generated this run")
        except Exception as e:
            db.session.rollback()
            _ag_log(f"✘ Commit error: {e}")


@signals_bp.route("/auto-generate/start", methods=["POST"])
@login_required
def ag_start():
    from app.extensions import scheduler
    data = request.get_json() or {}

    _AG_STATE.update({
        "running":          True,
        "market":           data.get("market", "crypto"),
        "timeframe":        data.get("timeframe", "1h"),
        "signal_filter":    data.get("signal_filter", "all"),
        "min_confidence":   float(data.get("min_confidence", 0)),
        "max_per_run":      int(data.get("max_per_run", 0)),
        "interval_minutes": int(data.get("interval_minutes", 5)),
        "runs": 0, "generated": 0, "errors": 0,
        "buy": 0, "sell": 0, "hold": 0,
        "last_run_at": None,
        "log": [],
    })

    app = current_app._get_current_object()

    # Remove existing job if any
    try:
        scheduler.remove_job(_AG_JOB_ID)
    except Exception:
        pass

    interval = _AG_STATE["interval_minutes"]
    if interval > 0:
        scheduler.add_job(
            _run_auto_generate,
            "interval",
            args=[app],
            id=_AG_JOB_ID,
            minutes=interval,
            replace_existing=True,
            next_run_time=datetime.utcnow(),  # run immediately on start
        )
    else:
        # Run once immediately
        import threading
        threading.Thread(target=_run_auto_generate, args=[app], daemon=True).start()

    _ag_log(f"Auto Generate started — {_AG_STATE['market']}/{_AG_STATE['timeframe']} every {interval}min")
    return jsonify({"status": "started"}), 200


@signals_bp.route("/auto-generate/stop", methods=["POST"])
@login_required
def ag_stop():
    from app.extensions import scheduler
    _AG_STATE["running"] = False
    _AG_STATE["next_run_at"] = None
    try:
        scheduler.remove_job(_AG_JOB_ID)
    except Exception:
        pass
    _ag_log("⏹ Auto Generate stopped")
    return jsonify({"status": "stopped"}), 200


@signals_bp.route("/auto-generate/status", methods=["GET"])
@login_required
def ag_status():
    return jsonify({
        "running":          _AG_STATE["running"],
        "market":           _AG_STATE["market"],
        "timeframe":        _AG_STATE["timeframe"],
        "interval_minutes": _AG_STATE["interval_minutes"],
        "runs":             _AG_STATE["runs"],
        "generated":        _AG_STATE["generated"],
        "buy":              _AG_STATE["buy"],
        "sell":             _AG_STATE["sell"],
        "hold":             _AG_STATE["hold"],
        "errors":           _AG_STATE["errors"],
        "last_run_at":      _AG_STATE["last_run_at"],
        "next_run_at":      _AG_STATE["next_run_at"],
        "log":              _AG_STATE["log"][-30:],
    }), 200


@signals_bp.route("/auto-generate/run-once", methods=["POST"])
@login_required
def ag_run_once():
    from app.extensions import scheduler
    data = request.get_json() or {}
    _AG_STATE.update({
        "market":         data.get("market",         _AG_STATE["market"]),
        "timeframe":      data.get("timeframe",      _AG_STATE["timeframe"]),
        "signal_filter":  data.get("signal_filter",  _AG_STATE["signal_filter"]),
        "min_confidence": float(data.get("min_confidence", _AG_STATE["min_confidence"])),
        "max_per_run":    int(data.get("max_per_run", _AG_STATE["max_per_run"])),
    })
    app = current_app._get_current_object()
    import threading
    threading.Thread(target=_run_auto_generate, args=[app], daemon=True).start()
    return jsonify({"status": "running"}), 200


@signals_bp.route("/mtf-matrix", methods=["GET"])
@login_required
def mtf_matrix():
    """
    Computes live indicator-based ratings per (asset, timeframe).
    Never returns — because ratings are derived from live OHLCV data, not DB signals.
    """
    from app.services.data.fetcher import market_fetcher
    from app.services.indicators.calculator import calculate_all_indicators
    from concurrent.futures import ThreadPoolExecutor
    from app.auth.decorators import get_current_user
    from app.models.user import UserAssetPreference

    user       = get_current_user()
    market     = request.args.get("market") or "all"
    ck         = f"mtf_matrix_{user.id}_{market}"
    cached     = cache.get(ck)
    if cached:
        return jsonify(cached), 200

    prefs = {p.asset_id: p.enabled for p in UserAssetPreference.query.filter_by(user_id=user.id).all()}

    timeframes = ["5m", "15m", "30m", "1h", "2h", "4h", "1d"]

    asset_q = Asset.query.filter_by(is_active=True)
    if market != "all":
        asset_q = asset_q.filter_by(market=market)
    all_assets = asset_q.order_by(Asset.market, Asset.symbol).all()
    assets = [a for a in all_assets if prefs.get(a.id, True)] if prefs else all_assets

    all_data = market_fetcher.fetch_many(assets, timeframes, limit=200)

    def _rate_asset(a):
        dfs = all_data.get(a.symbol, {})
        row = {}
        for tf in timeframes:
            try:
                df = dfs.get(tf)
                if df is None or len(df) < 52:
                    row[tf] = None
                    continue
                ind   = calculate_all_indicators(df)
                close = float(df["close"].iloc[-1])
                row[tf] = _mtf_rating(ind, close)
            except Exception:
                row[tf] = None
        return a.id, row

    matrix = {}
    with ThreadPoolExecutor(max_workers=min(8, len(assets))) as ex:
        for asset_id, row in ex.map(_rate_asset, assets):
            matrix[asset_id] = row

    payload = {
        "matrix": matrix,
        "assets": [{"id": a.id, "symbol": a.symbol, "name": a.name, "market": a.market} for a in assets],
        "timeframes": timeframes,
    }
    cache.set(ck, payload, timeout=120)
    return jsonify(payload), 200


def _mtf_rating(ind, close):
    """Score 12 indicators → BUY / SELL / HOLD signal with confidence %."""
    buy = sell = neutral = 0

    def vote(v):
        nonlocal buy, sell, neutral
        if v == "buy":     buy    += 1
        elif v == "sell":  sell   += 1
        else:              neutral += 1

    rsi = ind.get("rsi")
    if rsi is not None:
        vote("buy" if rsi < 30 else "sell" if rsi > 70 else "neutral")

    macd, macd_sig = ind.get("macd"), ind.get("macd_signal")
    if macd is not None and macd_sig is not None:
        vote("buy" if macd > macd_sig else "sell" if macd < macd_sig else "neutral")

    cci = ind.get("cci")
    if cci is not None:
        vote("buy" if cci < -100 else "sell" if cci > 100 else "neutral")

    roc = ind.get("roc")
    if roc is not None:
        vote("buy" if roc > 0 else "sell" if roc < 0 else "neutral")

    stoch_k = ind.get("stoch_rsi_k")
    if stoch_k is not None:
        vote("buy" if stoch_k < 20 else "sell" if stoch_k > 80 else "neutral")

    for ma_key in ["ema20", "ema50", "ema100", "ema200", "sma20", "sma50"]:
        ma = ind.get(ma_key)
        if ma:
            vote("buy" if close > ma else "sell")

    tenkan, kijun = ind.get("ichimoku_tenkan"), ind.get("ichimoku_kijun")
    if tenkan and kijun:
        vote("buy" if tenkan > kijun else "sell")

    bb_upper, bb_lower = ind.get("bb_upper"), ind.get("bb_lower")
    if bb_upper and bb_lower:
        vote("buy" if close < bb_lower else "sell" if close > bb_upper else "neutral")

    st_dir = ind.get("supertrend_direction")
    if st_dir:
        vote("buy" if st_dir == "up" else "sell")

    cmf = ind.get("cmf")
    if cmf is not None:
        vote("buy" if cmf > 0 else "sell" if cmf < 0 else "neutral")

    total = buy + sell + neutral
    if not total:
        return None

    score = (buy - sell) / total   # -1 … +1
    confidence = round(max(buy, sell) / total * 100)

    if score >= 0.5:    signal = "BUY"
    elif score <= -0.5: signal = "SELL"
    else:               signal = "HOLD"

    return {
        "signal_type": signal,
        "confidence":  confidence,
        "buy":         buy,
        "sell":        sell,
        "neutral":     neutral,
        "score":       round(score, 2),
    }


@signals_bp.route("/", methods=["GET"])
@login_required
def get_signals():
    market = request.args.get("market")
    timeframe = request.args.get("timeframe", "1h")
    signal_type = request.args.get("signal_type")
    min_confidence = float(request.args.get("min_confidence", 0))
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))

    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    query = Signal.query.join(Asset)
    if market:
        query = query.filter(Asset.market == market)
    if timeframe:
        query = query.filter(Signal.timeframe == timeframe)
    if signal_type:
        query = query.filter(Signal.signal_type == signal_type)
    if min_confidence:
        query = query.filter(Signal.confidence_score >= min_confidence)

    # Free users get delayed signals
    if user and user.subscription and user.subscription.signal_delay_minutes > 0:
        delay = user.subscription.signal_delay_minutes
        cutoff = datetime.utcnow() - timedelta(minutes=delay)
        query = query.filter(Signal.generated_at <= cutoff)

    signals = query.filter(Signal.status == "active") \
        .order_by(Signal.generated_at.desc()) \
        .paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "signals": [s.to_dict() for s in signals.items],
        "total": signals.total,
        "page": page,
        "pages": signals.pages,
    }), 200


@signals_bp.route("/<int:signal_id>", methods=["GET"])
@login_required
def get_signal(signal_id):
    signal = Signal.query.get_or_404(signal_id)
    return jsonify(signal.to_dict()), 200


@signals_bp.route("/generate", methods=["POST"])
@login_required
def generate_signal():
    data = request.get_json()
    symbol = data.get("symbol")
    timeframe = data.get("timeframe", "1h")

    asset = Asset.query.filter_by(symbol=symbol, is_active=True).first()
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    df = market_fetcher.fetch(asset, timeframe)
    if df is None:
        return jsonify({"error": "Failed to fetch market data"}), 503

    result = signal_engine.generate_signal(df, asset, timeframe)
    if not result:
        return jsonify({"error": "Could not generate signal"}), 422

    # AI boost
    try:
        from app.services.ai.predictor import ai_predictor
        prediction = ai_predictor.predict(df, asset.symbol, timeframe)
        result["ai_score"] = prediction.get("confidence", 50) * 0.2
        result["confidence_score"] = min(100, result["confidence_score"] + result["ai_score"] * 0.1)
    except Exception:
        pass

    signal = Signal(
        asset_id=asset.id,
        timeframe=timeframe,
        **{k: v for k, v in result.items()
           if k in ["signal_type", "entry_price", "stop_loss", "target1", "target2", "target3",
                    "risk_reward", "confidence_score", "confidence_label", "trend_score",
                    "momentum_score", "volume_score", "pattern_score", "ai_score",
                    "indicators", "patterns", "reasoning", "expires_at"]},
    )
    signal.set_confidence_label()
    db.session.add(signal)
    db.session.commit()

    return jsonify(signal.to_dict()), 201


@signals_bp.route("/summary", methods=["GET"])
@login_required
@cache.cached(timeout=60, key_prefix="signals_summary")
def get_summary():
    from sqlalchemy import func
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    counts = db.session.query(
        Signal.signal_type, func.count(Signal.id)
    ).filter(Signal.generated_at >= today).group_by(Signal.signal_type).all()

    summary = {t: c for t, c in counts}

    history = SignalHistory.query
    total_h = history.count()
    wins    = history.filter(SignalHistory.outcome == "win").count()
    win_rate = round((wins / total_h * 100), 1) if total_h else 0

    # Average confidence today
    avg_conf_row = db.session.query(func.avg(Signal.confidence_score)).filter(
        Signal.generated_at >= today).scalar()
    avg_confidence = round(float(avg_conf_row), 1) if avg_conf_row else 0

    # Top signal today (highest confidence, BUY or SELL only)
    top_signal_obj = Signal.query.join(Asset, Signal.asset_id == Asset.id).filter(
        Signal.generated_at >= today,
        Signal.signal_type.in_(["BUY", "SELL"])
    ).order_by(Signal.confidence_score.desc()).first()

    top_signal = None
    if top_signal_obj:
        asset = Asset.query.get(top_signal_obj.asset_id)
        top_signal = {
            "asset":            asset.symbol if asset else "?",
            "market":           asset.market if asset else "",
            "timeframe":        top_signal_obj.timeframe,
            "signal_type":      top_signal_obj.signal_type,
            "confidence_score": top_signal_obj.confidence_score,
        }

    # Open alerts (active signals)
    open_alerts = Signal.query.filter_by(status="active").count()

    return jsonify({
        "buy_today":       summary.get("BUY",  0),
        "sell_today":      summary.get("SELL", 0),
        "hold_today":      summary.get("HOLD", 0),
        "exit_today":      summary.get("EXIT", 0),
        "win_rate":        win_rate,
        "total_historical": total_h,
        "avg_confidence":  avg_confidence,
        "open_alerts":     open_alerts,
        "top_signal":      top_signal,
    }), 200


@signals_bp.route("/history", methods=["GET"])
@login_required
def signal_history():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    market = request.args.get("market")

    query = SignalHistory.query.join(Asset, SignalHistory.asset_id == Asset.id)
    if market:
        query = query.filter(Asset.market == market)

    history = query.order_by(SignalHistory.closed_at.desc()) \
        .paginate(page=page, per_page=per_page, error_out=False)

    asset_ids = {h.asset_id for h in history.items}
    assets_map = {a.id: a for a in Asset.query.filter(Asset.id.in_(asset_ids)).all()}

    items = []
    for h in history.items:
        asset = assets_map.get(h.asset_id)
        items.append({
            "id": h.id,
            "asset": asset.symbol if asset else "?",
            "timeframe": h.timeframe,
            "signal_type": h.signal_type,
            "entry": h.entry_price,
            "exit": h.exit_price,
            "pnl_pct": h.pnl_pct,
            "outcome": h.outcome,
            "confidence": h.confidence_score,
            "closed_at": h.closed_at.isoformat(),
        })

    return jsonify({
        "history": items,
        "total": history.total,
        "pages": history.pages,
    }), 200


@signals_bp.route("/analytics", methods=["GET"])
@login_required
def get_analytics():
    """Return signal performance analytics from Signal + SignalHistory tables."""

    # ── Overall stats ────────────────────────────────────────────────────────
    total_signals = Signal.query.count()
    active_count  = Signal.query.filter_by(status="active").count()
    closed_count  = Signal.query.filter(Signal.status != "active").count()

    hist_q    = SignalHistory.query
    total_h   = hist_q.count()
    wins      = hist_q.filter(SignalHistory.outcome == "hit_target").count()
    losses    = hist_q.filter(SignalHistory.outcome == "hit_sl").count()
    win_rate  = round(wins / total_h * 100, 1) if total_h else 0.0

    avg_rr_row = db.session.query(func.avg(Signal.risk_reward)).scalar()
    avg_rr     = round(float(avg_rr_row), 2) if avg_rr_row else 0.0

    # ── By market ────────────────────────────────────────────────────────────
    mkt_rows = (
        db.session.query(Asset.market, func.count(SignalHistory.id).label("total"))
        .join(SignalHistory, SignalHistory.asset_id == Asset.id)
        .group_by(Asset.market)
        .all()
    )
    by_market = []
    for mkt, total in mkt_rows:
        w = SignalHistory.query.join(Asset, SignalHistory.asset_id == Asset.id).filter(
            Asset.market == mkt, SignalHistory.outcome == "hit_target").count()
        l = SignalHistory.query.join(Asset, SignalHistory.asset_id == Asset.id).filter(
            Asset.market == mkt, SignalHistory.outcome == "hit_sl").count()
        by_market.append({
            "market": mkt, "total": total, "wins": w, "losses": l,
            "win_rate": round(w / total * 100, 1) if total else 0.0,
        })

    # ── By timeframe ─────────────────────────────────────────────────────────
    tf_rows = (
        db.session.query(SignalHistory.timeframe, func.count(SignalHistory.id).label("total"))
        .group_by(SignalHistory.timeframe)
        .all()
    )
    by_timeframe = []
    for tf, total in tf_rows:
        w = SignalHistory.query.filter_by(timeframe=tf, outcome="hit_target").count()
        by_timeframe.append({
            "timeframe": tf, "total": total, "wins": w,
            "win_rate": round(w / total * 100, 1) if total else 0.0,
        })

    # ── By signal type ───────────────────────────────────────────────────────
    st_rows = (
        db.session.query(SignalHistory.signal_type, func.count(SignalHistory.id).label("total"))
        .group_by(SignalHistory.signal_type)
        .all()
    )
    by_signal_type = []
    for st, total in st_rows:
        w = SignalHistory.query.filter_by(signal_type=st, outcome="hit_target").count()
        by_signal_type.append({
            "signal_type": st, "total": total, "wins": w,
            "win_rate": round(w / total * 100, 1) if total else 0.0,
        })

    # ── Confidence buckets ───────────────────────────────────────────────────
    confidence_buckets = []
    for lo, hi, label in [(50,60,"50-60%"),(60,70,"60-70%"),(70,80,"70-80%"),(80,90,"80-90%"),(90,101,"90-100%")]:
        rows = SignalHistory.query.filter(
            SignalHistory.confidence_score >= lo,
            SignalHistory.confidence_score < hi,
        )
        total = rows.count()
        w     = rows.filter(SignalHistory.outcome == "hit_target").count()
        confidence_buckets.append({
            "range": label, "total": total,
            "win_rate": round(w / total * 100, 1) if total else 0.0,
        })

    # ── Recent performance (last 30 days) ────────────────────────────────────
    cutoff = datetime.utcnow() - timedelta(days=30)
    recent_rows = (
        db.session.query(
            func.date(SignalHistory.closed_at).label("day"),
            func.count(SignalHistory.id).label("total"),
        )
        .filter(SignalHistory.closed_at >= cutoff)
        .group_by(func.date(SignalHistory.closed_at))
        .order_by(func.date(SignalHistory.closed_at))
        .all()
    )
    recent_performance = []
    for row in recent_rows:
        day_str = str(row.day)
        w = SignalHistory.query.filter(
            func.date(SignalHistory.closed_at) == row.day,
            SignalHistory.outcome == "hit_target",
        ).count()
        l = SignalHistory.query.filter(
            func.date(SignalHistory.closed_at) == row.day,
            SignalHistory.outcome == "hit_sl",
        ).count()
        recent_performance.append({"date": day_str, "signals": row.total, "wins": w, "losses": l})

    # ── Top assets (min 5 trades) ─────────────────────────────────────────────
    asset_rows = (
        db.session.query(Asset.symbol, Asset.market, func.count(SignalHistory.id).label("total"))
        .join(SignalHistory, SignalHistory.asset_id == Asset.id)
        .group_by(Asset.id, Asset.symbol, Asset.market)
        .having(func.count(SignalHistory.id) >= 5)
        .order_by(func.count(SignalHistory.id).desc())
        .limit(20)
        .all()
    )
    top_assets = []
    for sym, mkt, total in asset_rows:
        w = (
            SignalHistory.query
            .join(Asset, SignalHistory.asset_id == Asset.id)
            .filter(Asset.symbol == sym, SignalHistory.outcome == "hit_target")
            .count()
        )
        top_assets.append({
            "symbol": sym, "market": mkt, "total": total, "wins": w,
            "win_rate": round(w / total * 100, 1) if total else 0.0,
        })
    top_assets.sort(key=lambda x: x["win_rate"], reverse=True)

    return jsonify({
        "overall": {
            "total_signals": total_signals,
            "active": active_count,
            "closed": closed_count,
            "win_rate": win_rate,
            "avg_rr_achieved": avg_rr,
            "total_wins": wins,
            "total_losses": losses,
        },
        "by_market": by_market,
        "by_timeframe": by_timeframe,
        "by_signal_type": by_signal_type,
        "confidence_buckets": confidence_buckets,
        "recent_performance": recent_performance,
        "top_assets": top_assets,
    }), 200


@signals_bp.route("/export/csv", methods=["GET"])
@login_required
def export_signals_csv():
    """Export live signals as CSV."""
    market      = request.args.get("market")
    timeframe   = request.args.get("timeframe")
    signal_type = request.args.get("signal_type")
    status      = request.args.get("status", "active")

    query = Signal.query.join(Asset)
    if market:
        query = query.filter(Asset.market == market)
    if timeframe:
        query = query.filter(Signal.timeframe == timeframe)
    if signal_type:
        query = query.filter(Signal.signal_type == signal_type)
    if status:
        query = query.filter(Signal.status == status)

    signals = query.order_by(Signal.generated_at.desc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date","Asset","Market","Timeframe","Signal","Entry","Stop Loss",
                     "Target1","Target2","R:R","Confidence","Status","Reasoning"])
    for s in signals:
        writer.writerow([
            s.generated_at.strftime("%Y-%m-%d %H:%M") if s.generated_at else "",
            s.asset.symbol if s.asset else "",
            s.asset.market if s.asset else "",
            s.timeframe,
            s.signal_type,
            s.entry_price,
            s.stop_loss,
            s.target1,
            s.target2,
            round(s.risk_reward, 2) if s.risk_reward else "",
            round(s.confidence_score, 1) if s.confidence_score else "",
            s.status,
            s.reasoning or "",
        ])

    today = datetime.utcnow().strftime("%Y-%m-%d")
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=signals_{today}.csv"},
    )


@signals_bp.route("/history/export/csv", methods=["GET"])
@login_required
def export_history_csv():
    """Export signal history as CSV."""
    records = SignalHistory.query.order_by(SignalHistory.closed_at.desc()).all()
    asset_ids = {r.asset_id for r in records}
    assets_map = {a.id: a for a in Asset.query.filter(Asset.id.in_(asset_ids)).all()}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date","Asset","Market","Timeframe","Signal","Entry",
                     "Outcome","PnL%","Duration(min)","R:R Predicted"])
    for h in records:
        asset = assets_map.get(h.asset_id)
        # Approximate R:R from entry/stop_loss/target1
        predicted_rr = ""
        if h.entry_price and h.stop_loss and h.target1 and h.entry_price != h.stop_loss:
            predicted_rr = round(abs(h.target1 - h.entry_price) / abs(h.entry_price - h.stop_loss), 2)
        writer.writerow([
            h.closed_at.strftime("%Y-%m-%d %H:%M") if h.closed_at else "",
            asset.symbol if asset else "",
            asset.market if asset else "",
            h.timeframe,
            h.signal_type,
            h.entry_price,
            h.outcome,
            round(h.pnl_pct, 2) if h.pnl_pct is not None else "",
            h.duration_minutes or "",
            predicted_rr,
        ])

    today = datetime.utcnow().strftime("%Y-%m-%d")
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=signal_history_{today}.csv"},
    )
