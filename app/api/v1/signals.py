from flask import Blueprint, request, jsonify, current_app, Response
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from app.models.signal import Signal, SignalHistory
from app.models.asset import Asset
from app.models.user import User
from app.extensions import db, cache, limiter
from app.auth.decorators import login_required, admin_required, super_admin_required, premium_required, subscription_feature_required
from app.services.signals.engine import signal_engine, _EXPIRY as _SIGNAL_EXPIRY
from app.services.signals.context_lanes import fetch_context_data, build_lane_verdicts
from app.services.data.fetcher import market_fetcher
from datetime import datetime, timedelta
from sqlalchemy import and_, case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import csv
import io

logger = logging.getLogger(__name__)

signals_bp = Blueprint("signals", __name__)

# ── Persist auto-generate state across restarts (DB-backed singleton row) ─────
_AG_PERSIST_KEYS = (
    "running", "asset_ids", "markets", "timeframes", "signal_filter",
    "min_confidence", "max_per_run", "interval_minutes", "telegram_on_signal",
)

def _ag_save():
    try:
        from app.models.auto_generate_config import AutoGenerateConfig
        row = AutoGenerateConfig.query.first()
        if row is None:
            row = AutoGenerateConfig()
            db.session.add(row)
        for k in _AG_PERSIST_KEYS:
            setattr(row, k, _AG_STATE[k])
        db.session.commit()
    except Exception:
        db.session.rollback()

def _ag_load():
    try:
        from app.models.auto_generate_config import AutoGenerateConfig
        row = AutoGenerateConfig.query.first()
        return row.to_dict() if row else None
    except Exception:
        return None

# ── Cross-process status snapshot (Redis-backed via the shared Flask-Caching
# instance) ────────────────────────────────────────────────────────────────
# Auto-Generate only ever actually *runs* in the dedicated worker process
# (RUN_SCHEDULER=1) — the web tier's own _AG_STATE never executes a cycle,
# so after any web-tier restart it permanently shows the hardcoded initial
# values (running=False, all counters 0) no matter what the worker is
# really doing. ag_status() is answered by whichever tier happens to serve
# that HTTP request, so it publishes/reads through the cache (real Redis in
# production, shared by both containers) instead of trusting local memory.
_AG_STATUS_CACHE_KEY = "auto_generate:status_snapshot"
_AG_STATUS_KEYS = (
    "running", "asset_ids", "markets", "timeframes", "signal_filter",
    "min_confidence", "interval_minutes", "telegram_on_signal",
    "runs", "generated", "buy", "sell", "hold", "errors",
    "last_run_at", "next_run_at", "consecutive_empty_runs", "log",
)

def _ag_publish_status():
    try:
        cache.set(_AG_STATUS_CACHE_KEY, {k: _AG_STATE[k] for k in _AG_STATUS_KEYS}, timeout=3600)
    except Exception:
        pass

def _ag_status_snapshot():
    try:
        cached = cache.get(_AG_STATUS_CACHE_KEY)
        if cached:
            return cached
    except Exception:
        pass
    # Cold cache (nothing published since the last cache flush/restart, or
    # the schedule is currently stopped so no cycle is publishing a fresh
    # one) — the DB row is just as authoritative as a live snapshot for
    # the CONFIG fields, so read those from there instead of falling all
    # the way back to _AG_STATE's hardcoded defaults (interval=5,
    # timeframes=["1h"], ...), which would show the admin settings that
    # were never actually saved. Only the runtime counters
    # (runs/generated/.../log) have no other durable source and stay
    # zeroed — that's an accurate "nothing reported yet", not stale data.
    snap = {k: _AG_STATE[k] for k in _AG_STATUS_KEYS}
    saved = _ag_load()
    if saved:
        for k in _AG_PERSIST_KEYS:
            if k in saved:
                snap[k] = saved[k]
    return snap

def _ag_publish_partial(**updates):
    """Like _ag_publish_status(), but merges into the existing snapshot
    instead of overwriting it wholesale. Needed for ag_stop(): it runs in
    whichever tier answers that HTTP request, which is usually the web
    tier — its own local _AG_STATE counters (runs/generated/log/...) are
    permanently stale zeros there, so a blind overwrite would blank out
    real run history the worker had published just to flip one flag."""
    try:
        snap = _ag_status_snapshot()
        snap.update(updates)
        cache.set(_AG_STATUS_CACHE_KEY, snap, timeout=3600)
    except Exception:
        pass

# ── Server-side Auto Generate state ──────────────────────────────────────────
_AG_STATE = {
    # Watchlist config
    "running":           False,
    "asset_ids":         [],       # list of Asset.id — empty = all active (within selected markets)
    "markets":           [],       # list of market strings — empty = all markets
    "timeframes":        ["1h"],   # list of timeframe strings
    "signal_filter":     "all",
    "min_confidence":    0,
    "max_per_run":       0,
    "interval_minutes":  5,
    "telegram_on_signal": True,    # send Telegram for every new signal
    # Runtime counters (not persisted)
    "runs":                    0,
    "generated":               0,
    "errors":                  0,
    "buy":                     0,
    "sell":                    0,
    "hold":                    0,
    "last_run_at":             None,
    "next_run_at":             None,
    "log":                     [],
    "consecutive_empty_runs":  0,   # silence-failure detection
    "empty_streak_started_at": None,
    "empty_run_alert_sent_at": None,
}
_AG_JOB_ID = "user_auto_generate"


def _ag_log(msg):
    _AG_STATE["log"].append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")
    if len(_AG_STATE["log"]) > 100:
        _AG_STATE["log"] = _AG_STATE["log"][-100:]


def _run_auto_generate(app):
    with app.app_context():
        sig_filter  = _AG_STATE["signal_filter"]
        min_conf    = _AG_STATE["min_confidence"]
        max_per     = _AG_STATE["max_per_run"]
        timeframes  = _AG_STATE["timeframes"] or ["1h"]
        asset_ids   = _AG_STATE["asset_ids"]  # empty = all active (within markets)
        markets     = _AG_STATE.get("markets") or []  # empty = all markets
        tg_on_sig   = _AG_STATE["telegram_on_signal"]

        # Resolve watchlist assets — asset_ids and markets combine as AND filters
        asset_q = Asset.query.filter_by(is_active=True)
        if markets:
            asset_q = asset_q.filter(Asset.market.in_(markets))
        if asset_ids:
            asset_q = asset_q.filter(Asset.id.in_(asset_ids))
        assets = asset_q.all()

        combos = len(assets) * len(timeframes)
        _AG_STATE["runs"] += 1
        _AG_STATE["last_run_at"] = datetime.utcnow().isoformat()
        interval = _AG_STATE["interval_minutes"]
        _AG_STATE["next_run_at"] = (
            datetime.utcnow() + timedelta(minutes=interval)
        ).isoformat() if interval > 0 else None

        _ag_log(f"▶ Run #{_AG_STATE['runs']} — {len(assets)} assets × {len(timeframes)} TFs ({combos} combos)")
        count = 0

        # Fetch every (asset, timeframe) OHLCV frame in parallel up front —
        # each is an independent network round-trip (Yahoo/Delta/Binance)
        # with no shared mutable state, unlike the signal-generation +
        # DB-write step below which stays serial (SQLAlchemy session,
        # max_per early-break, and ordered logging aren't safely
        # parallelizable). This was previously N x M sequential fetches
        # blocking the whole run before any signal could be generated.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        combos_list = [(tf, asset) for tf in timeframes for asset in assets]
        df_by_combo = {}
        if combos_list:
            with ThreadPoolExecutor(max_workers=min(15, len(combos_list))) as pool:
                futures = {pool.submit(market_fetcher.fetch, asset, tf, 220): (tf, asset) for tf, asset in combos_list}
                for fut in as_completed(futures):
                    combo = futures[fut]
                    try:
                        df_by_combo[combo] = fut.result()
                    except Exception:
                        df_by_combo[combo] = None

        # Fetch News + EconomicEvent rows ONCE for this whole run — the
        # narrative/macro lanes below filter these in-memory per asset
        # instead of each issuing their own DB query across every combo.
        try:
            ctx = fetch_context_data()
        except Exception:
            ctx = {"news_items": [], "econ_events": []}

        for timeframe in timeframes:
            for asset in assets:
                if max_per and count >= max_per:
                    break
                # Captured up front: after a failed flush the session is in a
                # failed state, so touching asset.symbol inside the except block
                # triggers a lazy reload -> PendingRollbackError, which escaped
                # the handler and killed the whole job instead of skipping one
                # signal.
                symbol = asset.symbol
                try:
                    df = df_by_combo.get((timeframe, asset))
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

                    try:
                        result["lane_verdicts"] = build_lane_verdicts(
                            asset, result, ctx["news_items"], ctx["econ_events"])
                    except Exception:
                        pass

                    # Skip if this asset+timeframe already has ANY active signal.
                    # The uq_signals_active_asset_tf partial unique index permits
                    # at most one active signal per (asset, timeframe) with no
                    # time window, but this check also required
                    # generated_at >= lockout cutoff — so an active signal OLDER
                    # than the lockout passed the check and the INSERT below then
                    # failed with IntegrityError. Match the constraint exactly:
                    # any active signal means skip.
                    existing = Signal.query.filter(and_(
                        Signal.asset_id == asset.id,
                        Signal.timeframe == timeframe,
                        Signal.status == "active",
                    )).first()
                    if existing:
                        age = (int((datetime.utcnow() - existing.generated_at).total_seconds() / 60)
                               if existing.generated_at else 0)
                        _ag_log(f"  ~ {symbol}/{timeframe} skipped - active {age}m ago")
                        continue

                    sig = Signal(
                        asset_id=asset.id,
                        timeframe=timeframe,
                        **{k: v for k, v in result.items()
                           if k in ["signal_type","entry_price","stop_loss","target1","target2","target3",
                                    "risk_reward","confidence_score","confidence_label","trend_score",
                                    "momentum_score","volume_score","pattern_score","ai_score",
                                    "indicators","patterns","reasoning","reasoning_detail","regime","expires_at",
                                    "lane_verdicts","invalidation_conditions","target_allocations"]},
                    )
                    db.session.add(sig)
                    db.session.flush()

                    _AG_STATE["generated"] += 1
                    if stype == "BUY":    _AG_STATE["buy"]  += 1
                    elif stype == "SELL": _AG_STATE["sell"] += 1
                    else:                 _AG_STATE["hold"] += 1
                    count += 1
                    conf = result.get("confidence_score", 0)
                    _ag_log(f"  ✓ {asset.symbol}/{timeframe} → {stype} {conf:.0f}%")

                    # Telegram delivery for this signal is handled by
                    # fire_signal_alerts (notification_tasks.py), which polls
                    # the Signal table every 5 minutes — not sent immediately
                    # here. This used to ALSO fire its own Telegram send the
                    # instant a signal was generated, so anything picked up
                    # by both paths (the common case: fire_signal_alerts'
                    # confidence bar is typically at or below what reaches
                    # this point) went out as two separate Telegram messages
                    # for the same signal. tg_on_sig is kept as a stored
                    # setting for backward compatibility with existing saved
                    # configs, but no longer does anything — there's only
                    # one Telegram send path now.

                except IntegrityError:
                    # A concurrent run (or the scheduled generator) created an
                    # active signal for this asset+timeframe between the check
                    # above and this flush — the partial unique index rejected
                    # the duplicate. Benign: roll back and move on rather than
                    # counting it as an error.
                    db.session.rollback()
                    _ag_log(f"  ~ {symbol}/{timeframe} skipped - active signal already exists")
                except Exception as e:
                    # Roll back FIRST — after a failed flush the session is
                    # unusable and even building the log line below could raise.
                    db.session.rollback()
                    _AG_STATE["errors"] += 1
                    _ag_log(f"  x {symbol}/{timeframe}: {e}")

        try:
            db.session.commit()
            _ag_log(f"✔ Done — {count} signals generated this run")
        except Exception as e:
            db.session.rollback()
            _ag_log(f"✘ Commit error: {e}")

        # ── Silent failure detection ──────────────────────────────────────────
        # Gated on continuous wall-clock silence, not a fixed run count. A
        # fixed count (the old behavior — 5 consecutive empty runs) fires
        # after the same short window regardless of watchlist size or
        # polling interval, so a small watchlist (e.g. a handful of assets
        # on one timeframe) on a short interval trips it constantly during
        # perfectly normal quiet periods — real signals for a thin
        # watchlist can legitimately be hours apart. _MIN_EMPTY_RUNS still
        # guards the other direction: a long configured interval (e.g.
        # hourly) shouldn't alert off a single empty run just because that
        # one run already exceeds the silence window.
        _EMPTY_SILENCE_HOURS = 3
        _MIN_EMPTY_RUNS      = 3
        _ALERT_COOLDOWN_HOURS = 2  # don't re-alert within this window
        now = datetime.utcnow()
        if count == 0:
            _AG_STATE["consecutive_empty_runs"] = _AG_STATE.get("consecutive_empty_runs", 0) + 1
            if not _AG_STATE.get("empty_streak_started_at"):
                _AG_STATE["empty_streak_started_at"] = now.isoformat()
        else:
            _AG_STATE["consecutive_empty_runs"] = 0
            _AG_STATE["empty_streak_started_at"] = None
            _AG_STATE["empty_run_alert_sent_at"] = None

        streak_started = _AG_STATE.get("empty_streak_started_at")
        silent_hours = (
            (now - datetime.fromisoformat(streak_started)).total_seconds() / 3600
            if streak_started else 0
        )

        if _AG_STATE["consecutive_empty_runs"] >= _MIN_EMPTY_RUNS and silent_hours >= _EMPTY_SILENCE_HOURS:
            last_alert = _AG_STATE.get("empty_run_alert_sent_at")
            cooldown_ok = (
                last_alert is None or
                (now - datetime.fromisoformat(last_alert)).total_seconds() > _ALERT_COOLDOWN_HOURS * 3600
            )
            if cooldown_ok:
                _AG_STATE["empty_run_alert_sent_at"] = now.isoformat()
                _ag_log(f"⚠️ Alert: {silent_hours:.1f}h silent ({_AG_STATE['consecutive_empty_runs']} consecutive runs)")
                import threading
                def _send_failure_alert():
                    try:
                        with app.app_context():
                            from app.models.user import User
                            from app.models.notification import Notification
                            from app.tasks.notification_tasks import _send_telegram
                            n = _AG_STATE["consecutive_empty_runs"]
                            hrs = silent_hours
                            title = "⚠️ Auto-Generate Alert"
                            body = (
                                f"No signals generated in {hrs:.1f} hours ({n} consecutive runs). "
                                f"This may indicate an API issue, engine error, or over-filtering — "
                                f"or simply a quiet market for the current watchlist."
                            )
                            tg_text = (
                                f"⚠️ *Auto-Generate Alert*\n"
                                f"No signals generated in *{hrs:.1f} hours* ({n} consecutive runs).\n"
                                f"This may indicate an API issue, engine error, or over-filtering — "
                                f"or simply a quiet market for your current watchlist.\n"
                                f"Check the Auto-Generate log for details."
                            )
                            # This alert is about the admin-only Auto-Generate
                            # engine's own health — a regular subscriber has no
                            # access to that page or its log, so (like the
                            # new-IP-login alert) it only ever goes to super
                            # admins, not every telegram-enabled active user.
                            admins = User.query.filter_by(is_active=True, is_super_admin=True).all()
                            for admin in admins:
                                db.session.add(Notification(
                                    user_id=admin.id, title=title, message=body,
                                    notification_type="auto_generate_alert", channel="web",
                                ))
                                try:
                                    from app.websocket.events import broadcast_notification
                                    broadcast_notification(admin.id, title, body)
                                except Exception:
                                    pass
                                if admin.telegram_enabled and admin.telegram_chat_id:
                                    _send_telegram(admin, tg_text)
                                if admin.push_enabled and admin.push_subscription:
                                    try:
                                        from app.services.push import send_push_to_user
                                        send_push_to_user(admin, title, body, url="/auto-generate")
                                    except Exception:
                                        pass
                            db.session.commit()
                    except Exception as e:
                        logger.warning(f"Empty-run alert failed: {e}")
                threading.Thread(target=_send_failure_alert, daemon=True).start()

        _ag_publish_status()


def _parse_ag_config(data):
    """Shared parsing for auto-generate config payloads (start/save/run-once)."""
    raw_tfs = data.get("timeframes") or data.get("timeframe", "1h")
    timeframes = raw_tfs if isinstance(raw_tfs, list) else [raw_tfs]

    raw_markets = data.get("markets") or data.get("market") or []
    markets = raw_markets if isinstance(raw_markets, list) else ([raw_markets] if raw_markets else [])
    markets = [m for m in markets if m]  # drop empty strings

    asset_ids = data.get("asset_ids", [])

    return {
        "asset_ids":          [int(x) for x in asset_ids],
        "markets":            markets,
        "timeframes":         timeframes,
        "signal_filter":      data.get("signal_filter", "all"),
        "min_confidence":     float(data.get("min_confidence", 0)),
        "max_per_run":        int(data.get("max_per_run", 0)),
        "interval_minutes":   int(data.get("interval_minutes", 5)),
        "telegram_on_signal": bool(data.get("telegram_on_signal", True)),
    }


@signals_bp.route("/auto-generate/save", methods=["POST"])
@super_admin_required
def ag_save_config():
    """Persist Auto Generate settings to the DB without touching whether
    the schedule is running. _parse_ag_config() never includes "running",
    but _ag_save() persists every _AG_PERSIST_KEYS field — including it —
    from THIS process's local _AG_STATE. On the web tier that field is
    never the real running state (only the dedicated worker process
    actually executes a cycle and keeps it in sync — see
    _sync_auto_generate_from_db in app/__init__.py); it sits at its
    False default there. Without pulling the current value back from the
    DB first, a plain settings-only Save made from the web tier would
    silently persist running=False and kill an actually-running
    schedule the next time the worker polls this config — exactly the
    kind of "Auto-Generate randomly stopped" report this was causing.
    """
    data = request.get_json() or {}
    _AG_STATE.update(_parse_ag_config(data))
    saved = _ag_load()
    if saved is not None:
        _AG_STATE["running"] = bool(saved.get("running"))
    _ag_save()
    _ag_log("Configuration saved")
    return jsonify({"status": "saved", **_parse_ag_config(data)}), 200


@signals_bp.route("/auto-generate/start", methods=["POST"])
@super_admin_required
def ag_start():
    from app.extensions import scheduler
    data = request.get_json() or {}

    cfg = _parse_ag_config(data)
    timeframes = cfg["timeframes"]
    asset_ids  = cfg["asset_ids"]
    markets    = cfg["markets"]

    _AG_STATE.update({
        **cfg,
        "running": True,
        "runs": 0, "generated": 0, "errors": 0,
        "buy": 0, "sell": 0, "hold": 0,
        "last_run_at": None, "log": [],
    })

    app = current_app._get_current_object()
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
            next_run_time=datetime.utcnow(),
        )
    else:
        import threading
        threading.Thread(target=_run_auto_generate, args=[app], daemon=True).start()

    _ag_save()
    n_assets = len(asset_ids) if asset_ids else "all"
    mkt_label = "/".join(markets) if markets else "all markets"
    _ag_log(f"Auto Generate started — {n_assets} assets ({mkt_label}) × {timeframes} every {interval}min")
    # Publish immediately so ag_status() reflects "running" right away —
    # the actual scheduler that executes cycles lives in a different
    # container (the worker) and only picks this up on its next ~20s poll.
    _ag_publish_status()
    return jsonify({
        "status": "started", "asset_ids": _AG_STATE["asset_ids"],
        "markets": markets, "timeframes": timeframes,
    }), 200


@signals_bp.route("/auto-generate/stop", methods=["POST"])
@super_admin_required
def ag_stop():
    from app.extensions import scheduler
    # Pull the other config fields back from the DB before saving — same
    # reasoning as ag_save_config(): _ag_save() persists every
    # _AG_PERSIST_KEYS field from this process's local _AG_STATE, which on
    # the web tier can be stale for anything this action didn't just set
    # itself (e.g. timeframes changed by another replica/the worker's own
    # sync). Stop should only ever flip "running" off, never silently
    # revert unrelated settings to whatever this process last saw.
    saved = _ag_load()
    if saved is not None:
        _AG_STATE.update({k: saved[k] for k in _AG_PERSIST_KEYS if k in saved})
    _AG_STATE["running"] = False
    _AG_STATE["next_run_at"] = None
    try:
        scheduler.remove_job(_AG_JOB_ID)
    except Exception:
        pass
    _ag_save()
    _ag_log("⏹ Auto Generate stopped")
    _ag_publish_partial(running=False, next_run_at=None)
    return jsonify({"status": "stopped"}), 200


@signals_bp.route("/auto-generate/status", methods=["GET"])
@login_required
def ag_status():
    # Read through the shared cross-process snapshot (see _ag_publish_status)
    # instead of local _AG_STATE — this endpoint is answered by whichever
    # container took the HTTP request, which is usually the web tier, not
    # the worker process that's actually running the schedule.
    snap = _ag_status_snapshot()
    return jsonify({
        "running":            snap["running"],
        "asset_ids":          snap["asset_ids"],
        "markets":            snap.get("markets") or [],
        "timeframes":         snap["timeframes"],
        "signal_filter":      snap["signal_filter"],
        "min_confidence":     snap["min_confidence"],
        "interval_minutes":   snap["interval_minutes"],
        "telegram_on_signal": snap["telegram_on_signal"],
        "runs":               snap["runs"],
        "generated":          snap["generated"],
        "buy":                snap["buy"],
        "sell":               snap["sell"],
        "hold":               snap["hold"],
        "errors":                  snap["errors"],
        "last_run_at":             snap["last_run_at"],
        "next_run_at":             snap["next_run_at"],
        "consecutive_empty_runs":  snap.get("consecutive_empty_runs", 0),
        "log":                     snap["log"][-30:],
    }), 200


@signals_bp.route("/auto-generate/watchlist", methods=["GET"])
@login_required
def ag_watchlist():
    """Return all active assets grouped by market — used to build the asset picker."""
    assets = Asset.query.filter_by(is_active=True).order_by(Asset.market, Asset.symbol).all()
    selected = set(_AG_STATE["asset_ids"])
    return jsonify({
        "assets": [
            {**a.to_dict(), "selected": a.id in selected}
            for a in assets
        ],
        "markets": Asset.MARKETS,
        "selected_asset_ids": _AG_STATE["asset_ids"],
        "selected_markets": _AG_STATE.get("markets") or [],
        "selected_timeframes": _AG_STATE["timeframes"],
        "running": _AG_STATE["running"],
    }), 200


@signals_bp.route("/auto-generate/run-once", methods=["POST"])
@super_admin_required
def ag_run_once():
    data = request.get_json() or {}
    raw_tfs = data.get("timeframes") or data.get("timeframe")
    if raw_tfs:
        _AG_STATE["timeframes"] = raw_tfs if isinstance(raw_tfs, list) else [raw_tfs]
    if "asset_ids" in data:
        _AG_STATE["asset_ids"] = [int(x) for x in data["asset_ids"]]
    if "markets" in data or "market" in data:
        raw_markets = data.get("markets") or data.get("market") or []
        _AG_STATE["markets"] = raw_markets if isinstance(raw_markets, list) else ([raw_markets] if raw_markets else [])
    if "signal_filter" in data:
        _AG_STATE["signal_filter"] = data["signal_filter"]
    if "min_confidence" in data:
        _AG_STATE["min_confidence"] = float(data["min_confidence"])
    if "max_per_run" in data:
        _AG_STATE["max_per_run"] = int(data["max_per_run"])
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

    # ── Serve from pre-warmed global cache ───────────────────────
    global_mtf = cache.get("mtf_matrix_all")
    if global_mtf:
        prefs = {p.asset_id: p.enabled
                 for p in UserAssetPreference.query.filter_by(user_id=user.id).all()}
        assets = global_mtf["assets"]
        matrix = global_mtf["matrix"]
        if market != "all":
            assets = [a for a in assets if a.get("market") == market]
            matrix = {k: v for k, v in matrix.items()
                      if any(a["id"] == k for a in assets)}
        if prefs:
            assets = [a for a in assets if prefs.get(a["id"], True)]
            matrix = {k: v for k, v in matrix.items()
                      if any(a["id"] == k for a in assets)}
        return jsonify({"matrix": matrix, "assets": assets,
                        "timeframes": global_mtf["timeframes"]}), 200

    # ── Cold path ─────────────────────────────────────────────────
    prefs = {p.asset_id: p.enabled for p in UserAssetPreference.query.filter_by(user_id=user.id).all()}
    from app.services.indicators.ema_mtf import get_ta_timeframes
    timeframes = get_ta_timeframes()
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
                    row[tf] = None; continue
                # light=True: _mtf_rating only reads a specific subset of
                # indicator keys — see calculate_all_indicators' docstring.
                # Runs per asset x 7 timeframes, every 5-min prewarm cycle.
                ind   = calculate_all_indicators(df, light=True)
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
    # 330s — same reasoning as ta_summary_all: this route and
    # prewarm_ta_cache (data_tasks.py, every 5min/300s) share this cache
    # key; the cold-path re-cache here had never received the TTL fix
    # applied to the scheduled prewarm job and was still using 150s.
    cache.set("mtf_matrix_all", payload, timeout=330)
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


@signals_bp.route("/confluence/<int:asset_id>", methods=["GET"])
@login_required
def get_confluence(asset_id):
    """
    Compute per-timeframe confluence for an asset.
    Returns how many TFs align BUY vs SELL vs neutral.
    """
    from app.services.data.fetcher import market_fetcher
    from app.services.indicators.calculator import calculate_all_indicators

    asset = Asset.query.get_or_404(asset_id)

    ck = f"confluence_{asset_id}"
    cached = cache.get(ck)
    if cached:
        return jsonify(cached), 200

    from app.services.indicators.ema_mtf import get_ta_timeframes
    timeframes = get_ta_timeframes()

    # The prewarm job (data_tasks.py) already computes _mtf_rating for
    # every asset/timeframe into mtf_matrix_all every 5 minutes. If this
    # asset's row is present there, reuse it instead of re-fetching OHLCV
    # and re-running calculate_all_indicators from scratch for all 7
    # timeframes -- confluence is otherwise fully redundant with work the
    # prewarm job already did seconds/minutes ago.
    mtf_cached = cache.get("mtf_matrix_all")
    matrix_row = mtf_cached.get("matrix", {}).get(asset_id) if mtf_cached else None

    # Get primary signal direction from the most recent DB signal
    primary_signal = Signal.query.filter(
        Signal.asset_id == asset_id,
        Signal.status == "active",
        Signal.signal_type.in_(["BUY", "SELL"]),
    ).order_by(Signal.generated_at.desc()).first()
    primary_direction = primary_signal.signal_type if primary_signal else None

    buy_tfs = sell_tfs = neutral_tfs = 0
    tf_details = {}

    if matrix_row is not None:
        for tf in timeframes:
            rating = matrix_row.get(tf)
            if rating is None:
                neutral_tfs += 1
                tf_details[tf] = None
                continue
            sig = rating["signal_type"]
            tf_details[tf] = sig
            if sig == "BUY":
                buy_tfs += 1
            elif sig == "SELL":
                sell_tfs += 1
            else:
                neutral_tfs += 1
    else:
        all_data = market_fetcher.fetch_many([asset], timeframes, limit=100)
        dfs = all_data.get(asset.symbol, {})

        for tf in timeframes:
            try:
                df = dfs.get(tf)
                if df is None or len(df) < 52:
                    neutral_tfs += 1
                    tf_details[tf] = None
                    continue
                # light=True: also feeds _mtf_rating, same subset as mtf-matrix above.
                ind = calculate_all_indicators(df, light=True)
                close = float(df["close"].iloc[-1])
                rating = _mtf_rating(ind, close)
                if rating is None:
                    neutral_tfs += 1
                    tf_details[tf] = None
                    continue
                sig = rating["signal_type"]
                tf_details[tf] = sig
                if sig == "BUY":
                    buy_tfs += 1
                elif sig == "SELL":
                    sell_tfs += 1
                else:
                    neutral_tfs += 1
            except Exception:
                neutral_tfs += 1
                tf_details[tf] = None

    total = len(timeframes)
    dominant = "BUY" if buy_tfs >= sell_tfs else "SELL"
    dominant_count = max(buy_tfs, sell_tfs)
    confluence_str = f"{dominant_count}/{total} {dominant}"

    payload = {
        "asset_id": asset_id,
        "symbol": asset.symbol,
        "buy_tfs": buy_tfs,
        "sell_tfs": sell_tfs,
        "neutral_tfs": neutral_tfs,
        "total": total,
        "confluence": confluence_str,
        "primary_direction": primary_direction,
        "tf_details": tf_details,
    }
    cache.set(ck, payload, timeout=120)
    return jsonify(payload), 200


@signals_bp.route("/open-pnl", methods=["GET"])
@login_required
def open_pnl():
    """Return unrealized P&L for all active signals with live prices."""
    # This payload is entirely user-independent — the query below filters
    # only status="active" (no per-user filter), and user_id was previously
    # used *solely* to key the cache. A per-user key made every distinct user
    # re-run the whole DB read + parallel ticker fan-out (a Delta WS/REST hit
    # per unique crypto asset) even though the result is identical for all of
    # them. A single shared key lets the first request warm it for everyone
    # within the 30s window.
    cache_key = "open_pnl_all"
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached), 200

    active_signals = Signal.query.filter_by(status="active") \
        .order_by(Signal.generated_at.desc()).all()

    asset_ids  = {s.asset_id for s in active_signals}
    assets_map = {a.id: a for a in Asset.query.filter(Asset.id.in_(asset_ids)).all()}

    # Fetch each unique asset's ticker once, in parallel — was one
    # sequential fetch_ticker() call per SIGNAL (not per asset), so two
    # active signals on the same symbol/different timeframes paid for the
    # same live price twice, one after another.
    ticker_by_asset_id = {}
    if assets_map:
        with ThreadPoolExecutor(max_workers=min(15, len(assets_map))) as pool:
            futures = {pool.submit(market_fetcher.fetch_ticker, asset): asset_id
                       for asset_id, asset in assets_map.items()}
            for fut in as_completed(futures):
                asset_id = futures[fut]
                try:
                    ticker_by_asset_id[asset_id] = fut.result()
                except Exception:
                    ticker_by_asset_id[asset_id] = None

    now = datetime.utcnow()
    result = []
    for s in active_signals:
        asset = assets_map.get(s.asset_id)
        if not asset:
            continue

        current_price = None
        ticker = ticker_by_asset_id.get(s.asset_id)
        if ticker:
            current_price = float(
                ticker.get("last_price") or ticker.get("price") or ticker.get("close") or 0
            ) or None

        entry = float(s.entry_price or 0)
        pnl_pct = None
        if current_price and entry:
            if s.signal_type == "BUY":
                pnl_pct = (current_price - entry) / entry * 100
            elif s.signal_type == "SELL":
                pnl_pct = (entry - current_price) / entry * 100

        sl   = float(s.stop_loss or 0) or None
        tgt1 = float(s.target1   or 0) or None
        dist_sl  = None
        dist_t1  = None
        if current_price and sl and entry:
            dist_sl  = abs(current_price - sl)  / entry * 100
        if current_price and tgt1 and entry:
            dist_t1  = abs(tgt1 - current_price) / entry * 100

        age_hours = round((now - s.generated_at).total_seconds() / 3600, 1) if s.generated_at else None

        result.append({
            "signal_id":          s.id,
            "asset":              asset.symbol,
            "asset_id":           asset.id,
            "symbol":             asset.symbol,
            "timeframe":          s.timeframe,
            "signal_type":        s.signal_type,
            "entry_price":        entry,
            "current_price":      current_price,
            "pnl_pct":            round(pnl_pct, 2) if pnl_pct is not None else None,
            "stop_loss":          sl,
            "target1":            tgt1,
            "distance_to_sl_pct": round(dist_sl,  2) if dist_sl  is not None else None,
            "distance_to_t1_pct": round(dist_t1,  2) if dist_t1  is not None else None,
            "status":             s.status,
            "age_hours":          age_hours,
        })

    cache.set(cache_key, result, timeout=30)
    return jsonify(result), 200


@signals_bp.route("/", methods=["GET"])
@login_required
def get_signals():
    market = request.args.get("market")
    asset_id = request.args.get("asset_id", type=int)
    timeframe = request.args.get("timeframe")
    signal_type = request.args.get("signal_type")
    min_confidence = float(request.args.get("min_confidence", 0))
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))

    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    query = Signal.query.options(joinedload(Signal.asset)).join(Asset)
    if asset_id:
        query = query.filter(Signal.asset_id == asset_id)
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
@super_admin_required
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

    result = signal_engine.generate_signal(df, asset, timeframe, force=True)
    if not result:
        return jsonify({"error": "Could not generate signal — market conditions not met (low volatility or no clear direction)"}), 422

    # AI boost
    try:
        from app.services.ai.predictor import ai_predictor
        prediction = ai_predictor.predict(df, asset.symbol, timeframe)
        result["ai_score"] = prediction.get("confidence", 50) * 0.2
        result["confidence_score"] = min(100, result["confidence_score"] + result["ai_score"] * 0.1)
    except Exception:
        pass

    try:
        ctx = fetch_context_data()
        result["lane_verdicts"] = build_lane_verdicts(asset, result, ctx["news_items"], ctx["econ_events"])
    except Exception:
        pass

    signal = Signal(
        asset_id=asset.id,
        timeframe=timeframe,
        **{k: v for k, v in result.items()
           if k in ["signal_type", "entry_price", "stop_loss", "target1", "target2", "target3",
                    "risk_reward", "confidence_score", "confidence_label", "trend_score",
                    "momentum_score", "volume_score", "pattern_score", "ai_score",
                    "indicators", "patterns", "reasoning", "reasoning_detail", "regime", "expires_at",
                    "lane_verdicts", "invalidation_conditions", "target_allocations"]},
    )
    signal.set_confidence_label()
    db.session.add(signal)
    db.session.commit()

    return jsonify(signal.to_dict()), 201


@signals_bp.route("/dca-setup/<int:asset_id>", methods=["GET"])
@login_required
def dca_setup(asset_id):
    """Scaled-entry pullback setup state for one asset.

    Returns each entry rule's pass/fail on the last closed 5m candle plus the
    tranche ladder / TP / SL to use if it fires. See
    app/services/signals/dca_setup.py for the validated rule set and its
    measured performance.
    """
    from app.services.signals import dca_setup as setup

    asset = Asset.query.get_or_404(asset_id)
    # 2000 5m bars ≈ 666 15m bars — a proper warm-up for the 15m EMA200 the
    # rules depend on (200 15m bars minimum before it means anything).
    df = market_fetcher.fetch(asset, "5m", 2000)
    if df is None or len(df) < 700:
        have = 0 if df is None else len(df)
        return jsonify({"error": f"Need ~700 5m bars to warm up the 15m EMA200; "
                                 f"only {have} available for this asset."}), 503

    df = df.reset_index()
    tcol = next((c for c in ("ts", "timestamp", "index", "time")
                 if c in df.columns), None)
    if tcol and tcol != "ts":
        df = df.rename(columns={tcol: "ts"})

    result = setup.evaluate(df)
    result["asset"] = {"id": asset.id, "symbol": asset.symbol,
                       "name": asset.name, "market": asset.market}
    return jsonify(result), 200


@signals_bp.route("/position-analysis/<int:asset_id>", methods=["GET"])
@login_required
def position_analysis(asset_id):
    """
    Deeepr-style AI Position Analysis for a single asset: the most recent
    active BUY/SELL signal for this asset/timeframe (already carrying lane
    verdicts + invalidation conditions + target allocations from generation
    time), or — if none is active — a live, read-only analysis computed the
    same way the existing on-demand "Run AI Prediction" feature works on this
    page (not written to the DB).
    Query params: timeframe (default '1h')
    """
    asset = Asset.query.get_or_404(asset_id)
    timeframe = request.args.get("timeframe", "1h")

    active = Signal.query.filter(
        Signal.asset_id == asset_id,
        Signal.timeframe == timeframe,
        Signal.status == "active",
        Signal.signal_type.in_(["BUY", "SELL"]),
    ).order_by(Signal.generated_at.desc()).first()

    if active and active.lane_verdicts:
        payload = active.to_dict()
        payload["available"] = True
        payload["persisted"] = True
        return jsonify(payload), 200

    df = market_fetcher.fetch(asset, timeframe)
    if df is None:
        return jsonify({"available": False,
                         "message": "Market data unavailable for this asset/timeframe."}), 200

    # analyze() (unlike generate_signal) never returns None just because the
    # setup is too weak to alert on — it always packages lane scores/reasoning
    # so the preview panel has something to show. Session/volatility gates
    # (market closed, dead/chaotic data) are the only "truly nothing to show" cases.
    result = signal_engine.analyze(df, asset, timeframe)
    if not result.get("available"):
        reason_messages = {
            "market_closed": "Market is closed for this asset right now.",
            "no_indicators": "Not enough data to compute indicators yet.",
            "insufficient_data": "Not enough candle history yet.",
        }
        reason = result.get("reason", "")
        message = reason_messages.get(reason) or (
            "Volatility is outside a tradeable range right now."
            if reason.startswith("volatility_") else "No analysis available right now."
        )
        return jsonify({"available": False, "message": message}), 200

    try:
        ctx = fetch_context_data()
        result["lane_verdicts"] = build_lane_verdicts(asset, result, ctx["news_items"], ctx["econ_events"])
    except Exception:
        result["lane_verdicts"] = None
    result["available"] = True
    result["persisted"] = False
    result["asset"] = asset.symbol
    result["market"] = asset.market
    result["timeframe"] = timeframe
    return jsonify(result), 200


def _frozen_live_read(asset, timeframe, df):
    """A live-preview card (market_board() falls back to this when there's
    no persisted Signal for this asset+timeframe) still needs entry/stop/
    target numbers a user can actually read as a plan — but analyze()
    derives them from the CURRENT close price every time it's called, so
    calling it fresh on every request silently reshaped the "trade" (new
    entry, new stop, new targets) on every single page load. To a user
    watching the page, that's indistinguishable from a brand new signal
    replacing the old one every few seconds, even though nothing is
    actually being (re)generated or persisted — reported directly as
    "entry/stop/targets shouldn't change until TP or SL hits."

    Freezes analyze()'s BUY/SELL output the first time it's computed for
    this asset+timeframe and keeps serving that exact snapshot — only
    current_price stays live — until either the hypothetical trade would
    have actually resolved (price reaches the frozen stop-loss or final
    target, the same condition that would close a real persisted signal)
    or the timeframe's normal signal-validity window elapses. HOLD reads
    have no entry/stop/target numbers to freeze, so they're always
    computed fresh.
    """
    close = float(df["close"].iloc[-1])
    # The OHLCV candle's own close only moves when a candle actually
    # closes (once an hour for "1h", etc.) — using it as "current price"
    # made the price look frozen too between candle closes, which wasn't
    # noticeable before (entry/stop/targets moved in lockstep with it,
    # so *something* visibly changed) but became obvious once those were
    # frozen on their own schedule. fetch_ticker() is the same continuously-
    # updated live quote (WS stream for crypto, short-TTL cache otherwise)
    # the price ticker strip and open-P&L elsewhere in the app already use.
    live_price = close
    try:
        ticker = market_fetcher.fetch_ticker(asset)
        if ticker and ticker.get("price"):
            live_price = float(ticker["price"])
    except Exception:
        pass

    cache_key = f"terminal_live_read:{asset.id}:{timeframe}"
    cached = cache.get(cache_key)
    if cached:
        sl, t3, direction = cached.get("stop_loss"), cached.get("target3"), cached.get("signal_type")
        resolved = (
            (direction == "BUY"  and sl is not None and t3 is not None and (live_price <= sl or live_price >= t3)) or
            (direction == "SELL" and sl is not None and t3 is not None and (live_price >= sl or live_price <= t3))
        )
        if not resolved:
            cached["current_price"] = live_price
            return cached
        _close_live_read_log(cached.get("live_read_log_id"), live_price, direction, sl)

    result = signal_engine.analyze(df, asset, timeframe)
    if result.get("available") and result.get("signal_type") in ("BUY", "SELL"):
        result["current_price"] = live_price
        result["generated_at"] = datetime.utcnow().isoformat()
        result["live_read_log_id"] = _open_live_read_log(asset, timeframe, result)
        try:
            cache.set(cache_key, dict(result), timeout=_SIGNAL_EXPIRY.get(timeframe, 240) * 60)
        except Exception:
            pass
    elif result.get("available"):
        result["current_price"] = live_price
        result["generated_at"] = datetime.utcnow().isoformat()
    return result


def _open_live_read_log(asset, timeframe, result):
    """Records a fresh (not cache-hit) BUY/SELL live-preview read so its
    hypothetical performance can be measured — see LiveReadLog's own
    docstring for why this is tracked separately from real signals."""
    try:
        from app.models.live_read_log import LiveReadLog
        try:
            from app.services.ai.llm_reasoning import generate_reasoning
            llm_text = generate_reasoning(
                result["signal_type"], asset.symbol, timeframe,
                result.get("confidence_score") or 0, result.get("regime"), result.get("reasoning_detail"),
            )
            reasoning_text = llm_text or result.get("reasoning")
        except Exception:
            reasoning_text = result.get("reasoning")

        row = LiveReadLog(
            asset_id=asset.id, timeframe=timeframe, signal_type=result["signal_type"],
            confidence_score=result.get("confidence_score"), entry_price=result.get("entry_price"),
            stop_loss=result.get("stop_loss"), target1=result.get("target1"),
            target2=result.get("target2"), target3=result.get("target3"),
            reasoning=reasoning_text, reasoning_detail=result.get("reasoning_detail"),
            regime=result.get("regime"),
        )
        db.session.add(row)
        db.session.commit()
        return row.id
    except Exception:
        db.session.rollback()
        return None


def _close_live_read_log(log_id, exit_price, direction, stop_loss):
    """Marks a still-open LiveReadLog resolved once price actually reaches
    its frozen stop-loss or final target — same win/loss condition that
    would close a real persisted signal."""
    if not log_id:
        return
    try:
        from app.models.live_read_log import LiveReadLog
        row = LiveReadLog.query.get(log_id)
        if row and row.outcome is None:
            hit_stop = (
                (direction == "BUY"  and stop_loss is not None and exit_price <= stop_loss) or
                (direction == "SELL" and stop_loss is not None and exit_price >= stop_loss)
            )
            row.outcome = "loss" if hit_stop else "win"
            row.exit_price = exit_price
            row.resolved_at = datetime.utcnow()
            db.session.commit()
    except Exception:
        db.session.rollback()


@signals_bp.route("/market-board", methods=["GET"])
@login_required
def market_board():
    """
    One card per active asset in a market, for the selected timeframe —
    live BUY/SELL/HOLD read via signal_engine.analyze() (never blank the
    way persisted-signal listings are, since generate_signal() intentionally
    discards HOLD and low-conviction setups rather than writing a Signal row).
    Prefers a persisted active BUY/SELL signal when one already exists for
    an asset/timeframe (carries lane verdicts from generation time); falls
    back to a live analyze() read otherwise, same precedence as
    position_analysis() above.
    Query params: market (required), timeframe (default '1h')
    """
    market = request.args.get("market", "")
    timeframe = request.args.get("timeframe", "1h")
    if not market:
        return jsonify({"error": "market is required"}), 400

    from app.auth.decorators import get_current_user
    from app.models.user import UserAssetPreference

    all_assets = Asset.query.filter_by(is_active=True, market=market).order_by(Asset.symbol).all()
    # Respect the per-user "Analysis Assets" picker from Settings — same
    # opt-out preference model used by mtf_matrix() above. No rows for a
    # user means no preferences saved yet, so everything stays visible.
    user = get_current_user()
    prefs = {p.asset_id: p.enabled for p in UserAssetPreference.query.filter_by(user_id=user.id).all()}
    assets = [a for a in all_assets if prefs.get(a.id, True)] if prefs else all_assets
    if not assets:
        return jsonify({"cards": [], "total": 0}), 200

    active_by_asset = {
        s.asset_id: s for s in Signal.query.filter(
            Signal.asset_id.in_([a.id for a in assets]),
            Signal.timeframe == timeframe,
            Signal.status == "active",
            Signal.signal_type.in_(["BUY", "SELL"]),
        ).order_by(Signal.generated_at.desc()).all()
    }

    from concurrent.futures import ThreadPoolExecutor, as_completed
    need_fetch = [a for a in assets if a.id not in active_by_asset]
    df_by_asset = {}
    if need_fetch:
        with ThreadPoolExecutor(max_workers=min(15, len(need_fetch))) as pool:
            futures = {pool.submit(market_fetcher.fetch, a, timeframe): a for a in need_fetch}
            for fut in as_completed(futures):
                a = futures[fut]
                try:
                    df_by_asset[a.id] = fut.result()
                except Exception:
                    df_by_asset[a.id] = None

    cards = []
    for a in assets:
        sig = active_by_asset.get(a.id)
        if sig:
            payload = sig.to_dict()
            payload["available"] = True
            payload["persisted"] = True
        else:
            df = df_by_asset.get(a.id)
            if df is None:
                payload = {"available": False, "message": "Market data unavailable."}
            else:
                # Sequential, not parallel: analyze() reads the same shared
                # sklearn model cache used elsewhere in this codebase
                # (_model_mem_cache in predictor.py), which is not
                # thread-safe for concurrent .predict_proba() calls.
                result = _frozen_live_read(a, timeframe, df)
                if result.get("available"):
                    result["persisted"] = False
                else:
                    reason = result.get("reason", "")
                    reason_messages = {
                        "market_closed": "Market is closed for this asset right now.",
                        "no_indicators": "Not enough data to compute indicators yet.",
                        "insufficient_data": "Not enough candle history yet.",
                    }
                    result["message"] = reason_messages.get(reason) or (
                        "Volatility is too low to read right now — price is barely moving."
                        if reason.startswith("volatility_") else "No analysis available right now."
                    )
                payload = result
        payload["asset"] = a.symbol
        payload["asset_id"] = a.id
        payload["market"] = a.market
        payload["timeframe"] = timeframe
        cards.append(payload)

    return jsonify({"cards": cards, "total": len(cards)}), 200


# Fixed marketing set for the public landing page — no auth, so this must
# never leak reasoning/lane_verdicts/invalidation (paid-tier detail) or hit
# every asset (that's what /market-board + login is for). Same symbols the
# landing page's static ticker/sample-table used to hardcode.
_PUBLIC_TICKER_SYMBOLS = ["BTCUSDT", "ETHUSDT", "NIFTY50", "XAUUSD", "USDJPY", "BANKNIFTY", "TCS", "CLUSD"]
_PUBLIC_SIGNAL_SYMBOLS = ["BTCUSDT", "NIFTY50", "XAUUSD", "USDJPY"]


@signals_bp.route("/public-ticker", methods=["GET"])
@limiter.limit("90 per minute", override_defaults=True)
def public_ticker():
    """Unauthenticated live ticker strip for the landing page — symbol,
    price, % change only. No signal/entry/target data (that's paid detail).

    Polled every 5s by every public page's ticker widget (matches the 5s
    TTL of the underlying non-crypto price cache — see _TickerCache in
    app/services/data/fetcher.py) — that's 12 requests/minute from a
    single open tab, which blew straight through the app-wide default
    limit (500/hour) inside about 42 minutes for any real visitor who
    left the homepage open, not just under test load. override_defaults
    replaces the default tiers here rather than stacking on top of them,
    since 90/minute is already well above what any single visitor's
    ticker(s) can generate."""
    assets = Asset.query.filter(Asset.symbol.in_(_PUBLIC_TICKER_SYMBOLS)).all()
    by_symbol = {a.symbol: a for a in assets}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    items = []
    with ThreadPoolExecutor(max_workers=len(_PUBLIC_TICKER_SYMBOLS) or 1) as pool:
        futures = {pool.submit(market_fetcher.fetch_ticker, a): sym
                   for sym, a in by_symbol.items()}
        results = {}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                results[sym] = fut.result()
            except Exception:
                results[sym] = None

    for sym in _PUBLIC_TICKER_SYMBOLS:
        a = by_symbol.get(sym)
        if not a:
            continue
        t = results.get(sym)
        if not t or not t.get("price"):
            continue
        items.append({
            "symbol": sym,
            "name": a.name,
            "price": t["price"],
            "change_pct": t.get("change_pct", 0),
            "market": a.market,
        })

    return jsonify({"items": items}), 200


@signals_bp.route("/public-board", methods=["GET"])
def public_board():
    """Unauthenticated 'Today's Top Signals' teaser for the landing page —
    a fixed, small symbol set with signal type/confidence/entry/target1 only
    (no reasoning, lane verdicts, or invalidation — that detail is reserved
    for logged-in users). Reuses the same live analyze() read as
    /market-board so numbers are never fabricated."""
    assets = Asset.query.filter(Asset.symbol.in_(_PUBLIC_SIGNAL_SYMBOLS)).all()
    timeframe = "1h"

    from concurrent.futures import ThreadPoolExecutor, as_completed
    df_by_asset = {}
    with ThreadPoolExecutor(max_workers=len(assets) or 1) as pool:
        futures = {pool.submit(market_fetcher.fetch, a, timeframe): a for a in assets}
        for fut in as_completed(futures):
            a = futures[fut]
            try:
                df_by_asset[a.id] = fut.result()
            except Exception:
                df_by_asset[a.id] = None

    rows = []
    for a in assets:
        df = df_by_asset.get(a.id)
        if df is None:
            continue
        result = signal_engine.analyze(df, a, timeframe)
        if not result.get("available"):
            continue
        rows.append({
            "asset": a.symbol,
            "market": a.market,
            "timeframe": timeframe,
            "signal_type": result["signal_type"],
            "confidence_score": result.get("confidence_score", 0),
            "entry_price": result.get("entry_price"),
            "target1": result.get("target1"),
        })

    return jsonify({"rows": rows}), 200


@signals_bp.route("/public-stats", methods=["GET"])
def public_stats():
    """Unauthenticated platform activity stats for the landing page — scale
    numbers only (signals generated, assets covered, trades tracked), not a
    win-rate claim: this dev/mixed-history DB's raw win rate isn't a clean
    live track record and would be a misleading headline number."""
    total_signals = Signal.query.count()
    resolved = Signal.query.filter(Signal.status.in_(["hit_target", "hit_sl"])).count()
    assets = Asset.query.filter_by(is_active=True).count()
    markets = db.session.query(Asset.market).filter_by(is_active=True).distinct().count()
    from app.services.platform_config import get_platform_config
    timeframes = len(get_platform_config().get("timeframes") or [])
    return jsonify({
        "signals_generated": total_signals,
        "trades_tracked": resolved,
        "assets_covered": assets,
        "markets_covered": markets,
        "timeframes_covered": timeframes,
    }), 200


@signals_bp.route("/performance/by-asset", methods=["GET"])
@login_required
def signal_performance():
    """Signal outcome analytics from closed signal history, broken down by
    asset x timeframe with a configurable lookback window.

    NOTE: this used to be registered at the same URL as get_performance()
    below (both were "/performance") — Flask only ever routes to the
    later-registered view function for a given rule, so this one was
    completely unreachable dead code. Moved to its own path; the
    calibration data it computed is now merged into get_performance()
    (see _confidence_calibration_bands) since that's what the dashboard
    actually calls.

    Query params: ?days=<lookback, default 90> &market=<optional filter>
    """
    try:
        days = int(request.args.get("days", 90))
    except (TypeError, ValueError):
        days = 90
    market = request.args.get("market")

    cutoff = datetime.utcnow() - timedelta(days=days)
    q = SignalHistory.query.filter(SignalHistory.closed_at >= cutoff)
    rows = q.all()

    # Asset map (for symbol/market labels + optional market filter)
    asset_ids = {r.asset_id for r in rows if r.asset_id}
    assets_map = {a.id: a for a in Asset.query.filter(Asset.id.in_(asset_ids)).all()} if asset_ids else {}
    if market:
        rows = [r for r in rows if (a := assets_map.get(r.asset_id)) and a.market == market]

    def _stats(items):
        total = len(items)
        wins = [r for r in items if r.outcome == "win"]
        losses = [r for r in items if r.outcome == "loss"]
        gross_win = sum((r.pnl_pct or 0) for r in wins)
        gross_loss = abs(sum((r.pnl_pct or 0) for r in losses))
        return {
            "total": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / total * 100, 1) if total else 0,
            "avg_pnl_pct": round(sum((r.pnl_pct or 0) for r in items) / total, 3) if total else 0,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0
                             else (None if gross_win > 0 else 0),   # None = no losing trades
        }

    # ── Overall ──
    overall = _stats(rows)

    # ── Per asset × timeframe ──
    from collections import defaultdict
    buckets: dict[tuple, list] = defaultdict(list)
    for r in rows:
        buckets[(r.asset_id, r.timeframe)].append(r)
    by_asset_tf = []
    for (aid, tf), items in buckets.items():
        a = assets_map.get(aid)
        s = _stats(items)
        s.update({"asset": a.symbol if a else str(aid),
                  "market": a.market if a else None, "timeframe": tf})
        by_asset_tf.append(s)
    by_asset_tf.sort(key=lambda x: (-x["total"], -x["win_rate"]))

    # ── Confidence calibration: does an 80%-confidence signal win ~80%? ──
    conf_bands = [(0, 60, "Weak"), (60, 75, "Moderate"), (75, 90, "Strong"), (90, 101, "Very Strong")]
    calibration = []
    for lo, hi, label in conf_bands:
        band = [r for r in rows if lo <= (r.confidence_score or 0) < hi]
        decisive = [r for r in band if r.outcome in ("win", "loss")]
        actual_win = round(sum(1 for r in decisive if r.outcome == "win") / len(decisive) * 100, 1) \
                     if decisive else None
        calibration.append({
            "band": label, "range": f"{lo}-{hi - 1}",
            "signals": len(band),
            "actual_win_rate": actual_win,   # compare against the band midpoint
            "expected_win_rate": (lo + hi) // 2,
        })

    return jsonify({
        "lookback_days": days,
        "overall": overall,
        "by_asset_timeframe": by_asset_tf[:50],
        "calibration": calibration,
    }), 200


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
    # None (not 0) when there's no history yet — the frontend already
    # renders null as "—"; a literal 0 reads as "0% win rate" instead of
    # "no data yet", which is what avg_confidence below had been doing.
    win_rate = round((wins / total_h * 100), 1) if total_h else None

    # Closed-today breakdown — the dashboard's "Today's Summary" strip reads
    # these exact keys (closed_today/wins_today/losses_today/total_pnl_today)
    # but this endpoint never returned them, so those cells always fell
    # through every frontend fallback straight to "—".
    closed_today_q = SignalHistory.query.filter(SignalHistory.closed_at >= today)
    closed_today = closed_today_q.count()
    wins_today   = closed_today_q.filter(SignalHistory.outcome == "win").count()
    losses_today = closed_today_q.filter(SignalHistory.outcome == "loss").count()
    win_rate_today = round(wins_today / closed_today * 100, 1) if closed_today else None
    total_pnl_today_row = db.session.query(func.sum(SignalHistory.pnl_pct)).filter(
        SignalHistory.closed_at >= today).scalar()
    total_pnl_today = round(float(total_pnl_today_row), 2) if total_pnl_today_row else 0.0

    # Average confidence today — None when no signal has fired yet today,
    # not 0 (a thin watchlist can easily go hours into a new UTC day with
    # zero signals; "0.0%" reads as a real, alarmingly bad number instead
    # of "no data yet", which is what the frontend's null-check already
    # expects and Top Signal below already gets right).
    avg_conf_row = db.session.query(func.avg(Signal.confidence_score)).filter(
        Signal.generated_at >= today).scalar()
    avg_confidence = round(float(avg_conf_row), 1) if avg_conf_row else None

    # Top signal today (highest confidence, BUY or SELL only)
    top_signal_obj = Signal.query.join(Asset, Signal.asset_id == Asset.id).filter(
        Signal.generated_at >= today,
        Signal.signal_type.in_(["BUY", "SELL"])
    ).order_by(Signal.confidence_score.desc()).first()

    top_signal = None
    if top_signal_obj:
        # asset already joined above — access via relationship (joinedload not needed for single row)
        a = top_signal_obj.asset
        top_signal = {
            "asset":            a.symbol if a else "?",
            "market":           a.market if a else "",
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
        "closed_today":    closed_today,
        "wins_today":      wins_today,
        "losses_today":    losses_today,
        "win_rate_today":  win_rate_today,
        "total_pnl_today": total_pnl_today,
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

    outcome = request.args.get("outcome")
    query = SignalHistory.query.options(joinedload(SignalHistory.asset)).join(Asset, SignalHistory.asset_id == Asset.id)
    if market:
        query = query.filter(Asset.market == market)
    if outcome:
        query = query.filter(SignalHistory.outcome == outcome)

    history = query.order_by(SignalHistory.closed_at.desc()) \
        .paginate(page=page, per_page=per_page, error_out=False)

    items = []
    for h in history.items:
        a = h.asset
        items.append({
            "id":          h.id,
            "asset":       a.symbol if a else "?",
            "timeframe":   h.timeframe,
            "signal_type": h.signal_type,
            "entry":       h.entry_price,
            "exit":        h.exit_price,
            "pnl_pct":     h.pnl_pct,
            "outcome":     h.outcome,
            "confidence":  h.confidence_score,
            "duration_minutes": h.duration_minutes,
            "closed_at":   h.closed_at.isoformat() if h.closed_at else None,
        })

    return jsonify({
        "history": items,
        "total": history.total,
        "pages": history.pages,
    }), 200


@signals_bp.route("/analytics", methods=["GET"])
@login_required
# Deterministic, user-independent payload built from ~30 aggregate/count
# queries over Signal + SignalHistory (per market × timeframe × signal_type
# × confidence bucket × day). It takes no request args, so a shared 60s key
# is safe and collapses that whole fan-out for every dashboard poll — same
# pattern as get_summary above.
@cache.cached(timeout=60, key_prefix="signals_analytics")
def get_analytics():
    """Return signal performance analytics from Signal + SignalHistory tables."""

    # ── Overall stats ────────────────────────────────────────────────────────
    total_signals = Signal.query.count()
    active_count  = Signal.query.filter_by(status="active").count()
    closed_count  = Signal.query.filter(Signal.status != "active").count()

    hist_q    = SignalHistory.query
    total_h   = hist_q.count()
    wins      = hist_q.filter(SignalHistory.outcome == "win").count()
    losses    = hist_q.filter(SignalHistory.outcome == "loss").count()
    # None (not 0.0) with no history at all — this is the headline win_rate
    # every dashboard/markets/scanner KPI card reads and already treats
    # null as "—" vs. a real 0.0; see the identical fix in get_summary().
    win_rate  = round(wins / total_h * 100, 1) if total_h else None

    avg_rr_row = db.session.query(func.avg(Signal.risk_reward)).scalar()
    avg_rr     = round(float(avg_rr_row), 2) if avg_rr_row else None

    # Every section below used to run one GROUP BY for totals, then loop over
    # each group issuing 1-2 MORE queries for its win/loss count — 30-50 DB
    # round trips per cache miss on this file's busiest cached endpoint.
    # Conditional aggregation (SUM(CASE WHEN ... THEN 1 ELSE 0 END)) computes
    # totals AND wins/losses in the SAME GROUP BY query.
    wins_sum = func.sum(case((SignalHistory.outcome == "win", 1), else_=0))
    losses_sum = func.sum(case((SignalHistory.outcome == "loss", 1), else_=0))

    # ── By market ────────────────────────────────────────────────────────────
    mkt_rows = (
        db.session.query(Asset.market, func.count(SignalHistory.id).label("total"), wins_sum, losses_sum)
        .join(SignalHistory, SignalHistory.asset_id == Asset.id)
        .group_by(Asset.market)
        .all()
    )
    by_market = [{
        "market": mkt, "total": total, "wins": w or 0, "losses": l or 0,
        "win_rate": round((w or 0) / total * 100, 1) if total else 0.0,
    } for mkt, total, w, l in mkt_rows]

    # ── By timeframe ─────────────────────────────────────────────────────────
    tf_rows = (
        db.session.query(SignalHistory.timeframe, func.count(SignalHistory.id).label("total"), wins_sum)
        .group_by(SignalHistory.timeframe)
        .all()
    )
    by_timeframe = [{
        "timeframe": tf, "total": total, "wins": w or 0,
        "win_rate": round((w or 0) / total * 100, 1) if total else 0.0,
    } for tf, total, w in tf_rows]

    # ── By signal type ───────────────────────────────────────────────────────
    st_rows = (
        db.session.query(SignalHistory.signal_type, func.count(SignalHistory.id).label("total"), wins_sum)
        .group_by(SignalHistory.signal_type)
        .all()
    )
    by_signal_type = [{
        "signal_type": st, "total": total, "wins": w or 0,
        "win_rate": round((w or 0) / total * 100, 1) if total else 0.0,
    } for st, total, w in st_rows]

    # ── Confidence buckets ───────────────────────────────────────────────────
    # Bucketed with one CASE expression, grouped by that expression, instead
    # of 5 separate range-filtered queries (each doubled for its win count).
    bucket_bounds = [(50, 60, "50-60%"), (60, 70, "60-70%"), (70, 80, "70-80%"), (80, 90, "80-90%"), (90, 101, "90-100%")]
    bucket_expr = case(
        *[(and_(SignalHistory.confidence_score >= lo, SignalHistory.confidence_score < hi), label)
          for lo, hi, label in bucket_bounds],
        else_=None,
    )
    bucket_rows = dict(
        (label, (total, w))
        for label, total, w in db.session.query(bucket_expr, func.count(SignalHistory.id), wins_sum)
        .filter(bucket_expr.isnot(None))
        .group_by(bucket_expr)
        .all()
    )
    confidence_buckets = []
    for _, _, label in bucket_bounds:
        total, w = bucket_rows.get(label, (0, 0))
        confidence_buckets.append({
            "range": label, "total": total,
            "win_rate": round((w or 0) / total * 100, 1) if total else 0.0,
        })

    # ── Recent performance (last 30 days) ────────────────────────────────────
    cutoff = datetime.utcnow() - timedelta(days=30)
    recent_rows = (
        db.session.query(
            func.date(SignalHistory.closed_at).label("day"),
            func.count(SignalHistory.id).label("total"),
            wins_sum, losses_sum,
        )
        .filter(SignalHistory.closed_at >= cutoff)
        .group_by(func.date(SignalHistory.closed_at))
        .order_by(func.date(SignalHistory.closed_at))
        .all()
    )
    recent_performance = [
        {"date": str(day), "signals": total, "wins": w or 0, "losses": l or 0}
        for day, total, w, l in recent_rows
    ]

    # ── Top assets (min 5 trades) ─────────────────────────────────────────────
    asset_rows = (
        db.session.query(Asset.symbol, Asset.market, func.count(SignalHistory.id).label("total"), wins_sum)
        .join(SignalHistory, SignalHistory.asset_id == Asset.id)
        .group_by(Asset.id, Asset.symbol, Asset.market)
        .having(func.count(SignalHistory.id) >= 5)
        .order_by(func.count(SignalHistory.id).desc())
        .limit(20)
        .all()
    )
    top_assets = [{
        "symbol": sym, "market": mkt, "total": total, "wins": w or 0,
        "win_rate": round((w or 0) / total * 100, 1) if total else 0.0,
    } for sym, mkt, total, w in asset_rows]
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



@signals_bp.route("/performance", methods=["GET"])
@login_required
# Like get_analytics, this runs dozens of aggregate/count queries over
# SignalHistory (overall + per market/timeframe/type/confidence/day/hour +
# calibration) and takes no request args, so its output is deterministic and
# user-independent. A shared 60s key removes that fan-out from every repeat
# dashboard load — same pattern as get_summary.
@cache.cached(timeout=60, key_prefix="signals_performance")
def get_performance():
    """Personal performance dashboard — aggregated stats from SignalHistory."""

    # Same "None, not 0, when there's no data yet" rule applied consistently
    # below — already the intent for profit_factor's own comment further
    # down, just not carried through to the fields next to it. A literal 0
    # reads as "0% win rate" / "0 R:R" (a real, bad number) instead of "no
    # closed trades yet"; the frontend already treats null as "—" for every
    # one of these (win_rate/avg_rr/avg_pnl_pct confirmed against their
    # actual consumers — see get_summary()'s identical fix for the reasoning).
    hist_q = SignalHistory.query
    total_closed = hist_q.count()
    wins   = hist_q.filter(SignalHistory.outcome == "win").count()
    win_rate = round(wins / total_closed * 100, 1) if total_closed else None

    avg_rr_row = db.session.query(
        func.avg(Signal.risk_reward)
    ).join(SignalHistory, SignalHistory.signal_id == Signal.id).scalar()
    avg_rr = round(float(avg_rr_row), 2) if avg_rr_row else None

    total_pnl_row = db.session.query(func.sum(SignalHistory.pnl_pct)).scalar()
    total_pnl = round(float(total_pnl_row), 2) if total_pnl_row else 0.0
    avg_pnl_pct = round(total_pnl / total_closed, 3) if total_closed else None

    gross_win_row  = db.session.query(func.sum(SignalHistory.pnl_pct)).filter(SignalHistory.outcome == "win").scalar()
    gross_loss_row = db.session.query(func.sum(SignalHistory.pnl_pct)).filter(SignalHistory.outcome == "loss").scalar()
    gross_win  = float(gross_win_row) if gross_win_row else 0.0
    gross_loss = abs(float(gross_loss_row)) if gross_loss_row else 0.0
    # None (not 0) when there are no losing trades yet — "infinite" profit factor
    # is misleading as a raw number; the frontend renders None as "—".
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (None if gross_win > 0 else 0.0)

    avg_dur_row = db.session.query(func.avg(SignalHistory.duration_minutes)).scalar()
    avg_duration = int(avg_dur_row) if avg_dur_row else None

    best_row  = db.session.query(func.max(SignalHistory.pnl_pct)).scalar()
    worst_row = db.session.query(func.min(SignalHistory.pnl_pct)).scalar()
    best_win   = round(float(best_row),  2) if best_row  is not None else None
    worst_loss = round(float(worst_row), 2) if worst_row is not None else None

    # Every section below used to run one GROUP BY for trade counts, then loop
    # over each group issuing 1-2 MORE queries for its win count and/or avg
    # P&L — collapsed into one conditionally-aggregated query per section
    # (same fix as get_analytics above).
    wins_sum = func.sum(case((SignalHistory.outcome == "win", 1), else_=0))

    # ── By market ─────────────────────────────────────────────────────────────
    mkt_rows = (
        db.session.query(Asset.market, func.count(SignalHistory.id).label("trades"),
                         wins_sum, func.avg(SignalHistory.pnl_pct))
        .join(SignalHistory, SignalHistory.asset_id == Asset.id)
        .group_by(Asset.market).all()
    )
    by_market = [{
        "market": mkt, "trades": trades,
        "win_rate": round((w or 0) / trades * 100, 1) if trades else 0.0,
        "avg_pnl": round(float(avg_pnl), 2) if avg_pnl else 0.0,
    } for mkt, trades, w, avg_pnl in mkt_rows]

    # ── By timeframe ─────────────────────────────────────────────────────────
    tf_rows = (
        db.session.query(SignalHistory.timeframe, func.count(SignalHistory.id).label("trades"),
                         wins_sum, func.avg(SignalHistory.pnl_pct))
        .group_by(SignalHistory.timeframe).all()
    )
    by_timeframe = [{
        "timeframe": tf, "trades": trades,
        "win_rate": round((w or 0) / trades * 100, 1) if trades else 0.0,
        "avg_pnl": round(float(avg_pnl), 2) if avg_pnl else 0.0,
    } for tf, trades, w, avg_pnl in tf_rows]

    # ── By signal type ────────────────────────────────────────────────────────
    st_rows = (
        db.session.query(SignalHistory.signal_type, func.count(SignalHistory.id).label("trades"), wins_sum)
        .group_by(SignalHistory.signal_type).all()
    )
    by_signal_type = [{
        "type": st, "trades": trades,
        "win_rate": round((w or 0) / trades * 100, 1) if trades else 0.0,
    } for st, trades, w in st_rows]

    # ── By confidence bucket ──────────────────────────────────────────────────
    conf_bucket_bounds = [(50, 60, "50-60%"), (60, 70, "60-70%"), (70, 80, "70-80%"), (80, 90, "80-90%"), (90, 101, "90-100%")]
    conf_bucket_expr = case(
        *[(and_(SignalHistory.confidence_score >= lo, SignalHistory.confidence_score < hi), label)
          for lo, hi, label in conf_bucket_bounds],
        else_=None,
    )
    conf_bucket_rows = {
        label: (trades, w, avg_pnl)
        for label, trades, w, avg_pnl in db.session.query(
            conf_bucket_expr, func.count(SignalHistory.id), wins_sum, func.avg(SignalHistory.pnl_pct)
        ).filter(conf_bucket_expr.isnot(None)).group_by(conf_bucket_expr).all()
    }
    by_confidence = []
    for _, _, label in conf_bucket_bounds:
        trades, w, avg_pnl = conf_bucket_rows.get(label, (0, 0, None))
        by_confidence.append({
            "bucket": label, "trades": trades,
            "win_rate": round((w or 0) / trades * 100, 1) if trades else 0.0,
            "avg_pnl": round(float(avg_pnl), 2) if avg_pnl else 0.0,
        })

    # ── Daily P&L last 30 days ────────────────────────────────────────────────
    cutoff = datetime.utcnow() - timedelta(days=30)
    day_rows = (
        db.session.query(
            func.date(SignalHistory.closed_at).label("day"),
            func.count(SignalHistory.id).label("trades"),
            func.sum(SignalHistory.pnl_pct).label("pnl"),
            wins_sum,
        )
        .filter(SignalHistory.closed_at >= cutoff)
        .group_by(func.date(SignalHistory.closed_at))
        .order_by(func.date(SignalHistory.closed_at))
        .all()
    )
    daily_pnl = [{
        "date": str(day),
        "pnl_pct": round(float(pnl), 2) if pnl else 0.0,
        "trades": trades,
        "wins": w or 0,
    } for day, trades, pnl, w in day_rows]

    # ── Hourly win rate (UTC+5:30 = +330 min) ────────────────────────────────
    # strftime()/datetime(..., '+N minutes') are SQLite-only — Postgres has no
    # such functions, so this raised on every call there (this whole endpoint
    # had never run against Postgres before). The bucketing is cheap enough to
    # do in Python instead, which also sidesteps the dialect entirely rather
    # than trading one DB-specific expression for another.
    IST_OFFSET = 330
    try:
        closed_rows = (
            db.session.query(SignalHistory.closed_at, SignalHistory.outcome)
            .filter(SignalHistory.closed_at.isnot(None))
            .all()
        )
        hourly_buckets = {}
        for closed_at, outcome in closed_rows:
            hour = ((closed_at + timedelta(minutes=IST_OFFSET)).hour)
            trades, wins = hourly_buckets.get(hour, (0, 0))
            hourly_buckets[hour] = (trades + 1, wins + (1 if outcome == "win" else 0))
        hourly_win_rate = sorted((
            {"hour": hour, "win_rate": round(wins / trades * 100, 1) if trades else 0.0, "trades": trades}
            for hour, (trades, wins) in hourly_buckets.items()
        ), key=lambda x: x["hour"])
    except Exception:
        # A prior failed query in this same request can leave the session's
        # transaction aborted (Postgres refuses everything until it's rolled
        # back) — without this, the *next* query below would fail too,
        # turning one degraded chart into a 500 for the whole endpoint.
        db.session.rollback()
        hourly_win_rate = []

    # ── Confidence calibration: does an 80%-confidence signal actually win ~80%? ──
    # This used to live in a second, separately-registered `/performance`
    # route (`signal_performance`, now `_confidence_calibration_bands` below)
    # that Flask silently never routed to — both functions were bound to the
    # exact same URL rule, so only the later-registered one (this one) was
    # ever reachable, and the dashboard's Confidence Calibration chart
    # (dashboard.js `perf?.calibration`) always rendered empty.
    calibration = _confidence_calibration_bands()

    return jsonify({
        "overall": {
            "total_closed": total_closed,
            "win_rate": win_rate,
            "avg_rr": avg_rr,
            "total_pnl_pct": total_pnl,
            "avg_pnl_pct": avg_pnl_pct,
            "profit_factor": profit_factor,
            "avg_duration_minutes": avg_duration,
            "best_win_pct": best_win,
            "worst_loss_pct": worst_loss,
        },
        "by_market": by_market,
        "by_timeframe": by_timeframe,
        "by_signal_type": by_signal_type,
        "by_confidence": by_confidence,
        "calibration": calibration,
        "daily_pnl": daily_pnl,
        "hourly_win_rate": hourly_win_rate,
    }), 200


def _confidence_calibration_bands():
    """Do higher-confidence signals actually win more? Buckets closed
    signals by confidence band and compares actual win rate to the band's
    expected midpoint — the key measure of whether the confidence score is
    trustworthy. Extracted from the old signal_performance() so it can feed
    both /performance and any future dedicated endpoint."""
    rows = SignalHistory.query.all()
    conf_bands = [(0, 60, "Weak"), (60, 75, "Moderate"), (75, 90, "Strong"), (90, 101, "Very Strong")]
    calibration = []
    for lo, hi, label in conf_bands:
        band = [r for r in rows if lo <= (r.confidence_score or 0) < hi]
        decisive = [r for r in band if r.outcome in ("win", "loss")]
        actual_win = round(sum(1 for r in decisive if r.outcome == "win") / len(decisive) * 100, 1) \
                     if decisive else None
        calibration.append({
            "band": label, "range": f"{lo}-{hi - 1}",
            "signals": len(band),
            "actual_win_rate": actual_win,
            "expected_win_rate": (lo + hi) // 2,
        })
    return calibration


@signals_bp.route("/live-read-performance", methods=["GET"])
@login_required
@cache.cached(timeout=60, key_prefix="signals_live_read_performance")
def live_read_performance():
    """How well Terminal's live-preview cards (the non-persisted analyze()
    fallback, tracked in LiveReadLog — see _frozen_live_read) actually call
    it, separate from real generated-signal performance above. Useful for
    judging whether the board's "at a glance" reads are trustworthy on
    their own, not just as a stand-in for a real signal."""
    from app.models.live_read_log import LiveReadLog

    total = LiveReadLog.query.count()
    resolved_q = LiveReadLog.query.filter(LiveReadLog.outcome.isnot(None))
    resolved = resolved_q.count()
    wins = resolved_q.filter(LiveReadLog.outcome == "win").count()
    win_rate = round(wins / resolved * 100, 1) if resolved else None

    tf_rows = (
        db.session.query(
            LiveReadLog.timeframe, func.count(LiveReadLog.id),
            func.sum(case((LiveReadLog.outcome == "win", 1), else_=0)),
            func.sum(case((LiveReadLog.outcome.isnot(None), 1), else_=0)),
        ).group_by(LiveReadLog.timeframe).all()
    )
    by_timeframe = [{
        "timeframe": tf, "total": total_n, "resolved": res_n,
        "win_rate": round(w / res_n * 100, 1) if res_n else None,
    } for tf, total_n, w, res_n in tf_rows]

    return jsonify({
        "total_logged": total,
        "resolved": resolved,
        "open": total - resolved,
        "win_rate": win_rate,
        "by_timeframe": by_timeframe,
    }), 200


def _signal_outcome_label(status: str) -> str | None:
    return {"hit_target": "win", "hit_sl": "loss", "expired": "neutral"}.get(status)


def _build_retrospective_note(direction: str, outcome: str | None, reasoning_detail) -> str:
    """Plain-language "did the thesis hold up" sentence built entirely from
    data already computed and persisted at generation time — the reasoning
    factors that actually supported the final call (reasoning_detail's
    `aligned` flag — see SignalEngine._labeled_reasons) plus the real
    outcome. No new analysis happens here, just narrating what's already
    on the row for a human (or a future review of what went wrong) to
    read without re-deriving it from raw scores."""
    aligned = [r["text"] for r in (reasoning_detail or []) if r.get("aligned")][:3]
    thesis = "; ".join(aligned) if aligned else "no strongly supporting factors were recorded"
    side = "long" if direction == "BUY" else "short"
    if outcome is None:
        return f"Still open — {side} thesis: {thesis}."
    if outcome == "win":
        return f"Correct call — {side} thesis ({thesis}) played out; target was reached."
    if outcome == "loss":
        return f"Incorrect — {side} thesis was {thesis}, but price moved against the position and hit the stop instead."
    return f"Expired without resolving either way — {side} thesis was {thesis}, but neither target nor stop was hit before it timed out."


@signals_bp.route("/journal", methods=["GET"])
@login_required
def signal_journal():
    """Unified, human-readable record of every signal this platform has
    generated — both Auto-Generate's persisted Signal rows (which keep
    their full reasoning even after closing — see Signal.status) and
    Terminal's live-preview reads (LiveReadLog) — with the original
    rationale and, for anything resolved, a plain-language retrospective
    on whether that thesis actually held up. This is the "why was this
    taken, and were we right" record, not just another signal list.
    """
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 30)), 1), 100)
    market = request.args.get("market") or None
    timeframe = request.args.get("timeframe") or None
    outcome_filter = request.args.get("outcome") or None   # win, loss, neutral, open
    source_filter = request.args.get("source") or None     # auto_generate, terminal

    entries = []

    if source_filter != "terminal":
        q = Signal.query.filter(Signal.signal_type.in_(["BUY", "SELL"]))
        if timeframe:
            q = q.filter(Signal.timeframe == timeframe)
        rows = q.order_by(Signal.generated_at.desc()).limit(400).all()
        asset_ids = {r.asset_id for r in rows}
        assets_map = {a.id: a for a in Asset.query.filter(Asset.id.in_(asset_ids)).all()}
        for s in rows:
            a = assets_map.get(s.asset_id)
            if not a or (market and a.market != market):
                continue
            outcome = _signal_outcome_label(s.status)
            entries.append({
                "source": "auto_generate", "id": s.id,
                "asset": a.symbol, "asset_id": a.id, "market": a.market,
                "timeframe": s.timeframe, "signal_type": s.signal_type,
                "confidence_score": s.confidence_score, "confidence_label": s.confidence_label,
                "entry_price": s.entry_price, "stop_loss": s.stop_loss,
                "target1": s.target1, "target2": s.target2, "target3": s.target3,
                "pnl_pct": s.pnl_pct, "reasoning": s.reasoning, "reasoning_detail": s.reasoning_detail,
                "regime": s.regime, "status": s.status, "outcome": outcome,
                "generated_at": s.generated_at.isoformat() if s.generated_at else None,
                "retrospective_note": _build_retrospective_note(s.signal_type, outcome, s.reasoning_detail),
            })

    if source_filter != "auto_generate":
        from app.models.live_read_log import LiveReadLog
        q = LiveReadLog.query
        if timeframe:
            q = q.filter(LiveReadLog.timeframe == timeframe)
        rows = q.order_by(LiveReadLog.generated_at.desc()).limit(400).all()
        for r in rows:
            a = r.asset
            if not a or (market and a.market != market):
                continue
            entries.append({
                "source": "terminal", "id": r.id,
                "asset": a.symbol, "asset_id": a.id, "market": a.market,
                "timeframe": r.timeframe, "signal_type": r.signal_type,
                "confidence_score": r.confidence_score, "confidence_label": None,
                "entry_price": r.entry_price, "stop_loss": r.stop_loss,
                "target1": r.target1, "target2": r.target2, "target3": r.target3,
                "pnl_pct": None, "reasoning": r.reasoning, "reasoning_detail": r.reasoning_detail,
                "regime": r.regime, "status": "open" if r.outcome is None else "closed", "outcome": r.outcome,
                "generated_at": r.generated_at.isoformat() if r.generated_at else None,
                "retrospective_note": _build_retrospective_note(r.signal_type, r.outcome, r.reasoning_detail),
            })

    if outcome_filter:
        entries = [e for e in entries
                   if (e["outcome"] == outcome_filter) or (outcome_filter == "open" and e["outcome"] is None)]

    entries.sort(key=lambda e: e["generated_at"] or "", reverse=True)
    total = len(entries)
    start = (page - 1) * per_page
    page_items = entries[start:start + per_page]

    return jsonify({
        "entries": page_items,
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
        "page": page,
    }), 200


# ─── Backtest & Proof-of-Performance ──────────────────────────────────────────

@signals_bp.route("/history-stats", methods=["GET"])
@login_required
# Same rationale as get_analytics/get_performance/get_summary in this file:
# no request args, deterministic and user-independent output, but this was
# the one endpoint of the four with NO caching at all — every hit ran an
# unconditional SignalHistory.query.all() (unbounded — the table is only
# implicitly capped by nightly_cleanup's 60-day retention, not a query limit).
@cache.cached(timeout=60, key_prefix="signals_history_stats")
def history_stats():
    """
    Proven performance from real closed signals (SignalHistory), with both the
    dashboard-style raw win rate and the true win rate (excluding undecided
    trades). Includes a 'what-if' expiry diagnostic.
    """
    from app.services.backtest import analyze_history, whatif_expiry
    # Fetch SignalHistory once and share it with both functions — they
    # previously each ran their own independent unbounded query (3 full
    # loads of the same table across the two calls) on every request.
    rows = SignalHistory.query.all()
    return jsonify({
        "stats": analyze_history(rows),
        "whatif_expiry": whatif_expiry(rows),
    }), 200


@signals_bp.route("/backtest", methods=["GET"])
@premium_required
@subscription_feature_required("backtesting_enabled")
def backtest():
    """
    Walk-forward backtest that replays historical candles through the live
    signal engine and simulates target/stop hits — the source of truth for
    tuning. Query params:
      asset_id   — backtest a single asset (optional)
      timeframe  — required, e.g. 1h
      days       — history depth (default 60)
      market     — restrict portfolio backtest to one market (optional)
      limit      — max assets for portfolio backtest (default 15)
    Without asset_id it runs a portfolio backtest across active assets.
    """
    from app.services.backtest import run_backtest, backtest_portfolio

    timeframe = request.args.get("timeframe", "1h")
    days      = request.args.get("days", default=60, type=int)
    asset_id  = request.args.get("asset_id", type=int)
    symbol    = request.args.get("symbol", "").upper().strip()

    # Allow lookup by symbol string (used by the backtesting UI)
    if not asset_id and symbol:
        a = Asset.query.filter(Asset.symbol.ilike(symbol), Asset.is_active == True).first()
        if not a:
            return jsonify({"error": f"Asset '{symbol}' not found. Check the symbol and try again."}), 404
        asset_id = a.id

    if asset_id:
        asset = Asset.query.get_or_404(asset_id)
        result = run_backtest(asset, timeframe, days=days)
        # Normalise trade keys for the UI (add 'r' field). run_backtest()
        # returns its trade sample under "sample_trades" — this was
        # previously reading "trades_data" (a key that belongs to the
        # other, strategy-config backtest engine and never exists on this
        # result), which silently made this loop a no-op and left the
        # frontend's equity-curve chart and trade table permanently empty
        # for every live-engine backtest.
        for t in result.get("sample_trades", []):
            if "r" not in t and t.get("pnl_pct") is not None:
                t["r"] = round(t["pnl_pct"] / 100, 4)
        return jsonify(result), 200

    # Portfolio backtest — bounded to keep runtime reasonable.
    market = request.args.get("market")
    limit  = request.args.get("limit", default=15, type=int)
    q = Asset.query.filter_by(is_active=True)
    if market:
        q = q.filter_by(market=market)
    assets = q.order_by(Asset.market, Asset.symbol).limit(limit).all()

    return jsonify(backtest_portfolio(assets, timeframe, days=days)), 200


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
