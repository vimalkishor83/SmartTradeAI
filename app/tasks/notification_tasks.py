"""Background jobs for sending notifications."""
import logging

logger = logging.getLogger(__name__)


def send_pending_notifications(app):
    with app.app_context():
        from app.models.notification import Notification
        from app.models.user import User
        from app.extensions import db
        from datetime import datetime

        pending = Notification.query.filter_by(is_sent=False).limit(50).all()
        if not pending:
            return

        # Batch-fetch every referenced user in one query instead of one
        # SELECT per notification (was a straightforward N+1 — with users in
        # the thousands and >50 pending notifications per poll, this alone
        # was 50 extra round-trips every 30 seconds).
        user_ids = {n.user_id for n in pending}
        users_by_id = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()}

        for notif in pending:
            user = users_by_id.get(notif.user_id)
            if not user:
                continue
            try:
                if user.email_notifications and notif.channel in ("email", None):
                    _send_email(user.email, notif.title, notif.message)
                if user.telegram_enabled and user.telegram_chat_id:
                    _send_telegram(user.telegram_chat_id, f"*{notif.title}*\n{notif.message}")
                notif.is_sent = True
                notif.sent_at = datetime.utcnow()
            except Exception as e:
                logger.error(f"Notification send failed: {e}")

        db.session.commit()


def _send_email(to_email: str, subject: str, body: str):
    # Routed through the shared mailer service (Flask-Mail) so this respects
    # MAIL_SUPPRESS_SEND the same way verification/reset emails do — this
    # previously duplicated its own raw smtplib connection with no
    # suppression, so every deploy without SMTP creds configured logged a
    # noisy "Email send error" on every single pending notification.
    from app.services.mailer import send_email
    send_email(to_email, subject, body)


def _send_telegram(chat_id: str, text: str):
    try:
        import requests
        from flask import current_app
        token = current_app.config.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


def fire_signal_alerts(app):
    """
    Alert engine — runs every 5 minutes.
    Checks for:
      1. New high-confidence signals (≥ 75%) generated in the last 5 min
      2. Signal closed events (TP/SL hit) for all users

    Creates Notification rows + broadcasts WebSocket push + sends email/telegram.
    Dedup: one bulk query for existing notifications in the window — no per-signal N+1.
    """
    with app.app_context():
        from app.models.signal import Signal, SignalHistory
        from app.models.notification import Notification
        from app.models.user import User
        from app.models.asset import Asset
        from app.extensions import db
        from datetime import datetime, timedelta

        cutoff = datetime.utcnow() - timedelta(minutes=6)

        users = User.query.filter_by(is_active=True).all()
        if not users:
            return
        user_ids = [u.id for u in users]

        # ── Pre-fetch all recent notifications in one query (dedup without N+1) ──
        recent_notifs = Notification.query.filter(
            Notification.user_id.in_(user_ids),
            Notification.notification_type.in_(["signal_alert", "signal_closed"]),
            Notification.created_at >= cutoff,
        ).all()
        # Set of (user_id, notification_type, asset_symbol) already sent this window
        already_sent = {(n.user_id, n.notification_type, n.asset_symbol) for n in recent_notifs}

        # ── 1. New high-confidence signals ──────────────────────────
        # Respect the min_confidence threshold set in auto-generate config
        try:
            from app.api.v1.signals import _AG_STATE as _ags
            min_conf_threshold = max(float(_ags.get("min_confidence", 0)), 50)
        except Exception:
            min_conf_threshold = 75

        new_sigs = Signal.query.filter(
            Signal.generated_at >= cutoff,
            Signal.confidence_score >= min_conf_threshold,
            Signal.signal_type.in_(["BUY", "SELL"]),
            Signal.status == "active",
        ).all()

        sig_asset_ids = {s.asset_id for s in new_sigs}
        sig_assets = {a.id: a for a in Asset.query.filter(Asset.id.in_(sig_asset_ids)).all()} if sig_asset_ids else {}

        new_notifs = []
        for sig in new_sigs:
            asset = sig_assets.get(sig.asset_id)
            if not asset:
                continue
            title = f"{'🟢' if sig.signal_type == 'BUY' else '🔴'} {sig.signal_type} Signal: {asset.symbol}"
            msg   = (
                f"{asset.symbol} {sig.signal_type} @ {sig.entry_price:.4f} | "
                f"TF: {sig.timeframe} | Conf: {sig.confidence_score:.0f}% | "
                f"SL: {sig.stop_loss:.4f} | T1: {sig.target1:.4f}"
            )
            for user in users:
                key = (user.id, "signal_alert", asset.symbol)
                if key in already_sent:
                    continue
                already_sent.add(key)
                new_notifs.append(Notification(
                    user_id=user.id, title=title, message=msg,
                    notification_type="signal_alert", channel="web",
                    asset_symbol=asset.symbol,
                ))
                try:
                    from app.websocket.events import broadcast_notification
                    broadcast_notification(user.id, title, msg)
                except Exception:
                    pass
                if user.telegram_enabled and user.telegram_chat_id:
                    tg_msg = (
                        f"{'🟢' if sig.signal_type == 'BUY' else '🔴'} *{sig.signal_type} Signal: {asset.symbol}*\n"
                        f"Entry: `{sig.entry_price:.4f}` | TF: {sig.timeframe} | Conf: {sig.confidence_score:.0f}%\n"
                        f"SL: `{sig.stop_loss:.4f}` | T1: `{sig.target1:.4f}`"
                    )
                    _send_telegram(user.telegram_chat_id, tg_msg)
                if user.push_enabled and user.push_subscription:
                    try:
                        from app.services.push import send_push_to_user
                        send_push_to_user(user, title, msg, url="/dashboard/signals")
                    except Exception:
                        pass

        # ── 2. Signal close events (TP/SL hit) ──────────────────────
        recent_closes = SignalHistory.query.filter(
            SignalHistory.closed_at >= cutoff,
            SignalHistory.outcome.in_(["win", "loss"]),
        ).all()

        close_asset_ids = {h.asset_id for h in recent_closes}
        assets_closed = {a.id: a for a in Asset.query.filter(Asset.id.in_(close_asset_ids)).all()} if close_asset_ids else {}

        for h in recent_closes:
            asset = assets_closed.get(h.asset_id)
            if not asset:
                continue
            won   = h.outcome == "win"
            title = f"{'🏆' if won else '🛑'} Signal {'Hit Target' if won else 'Hit Stop Loss'}: {asset.symbol}"
            msg   = (
                f"{asset.symbol} {h.signal_type} closed at {h.exit_price:.4f} | "
                f"P&L: {h.pnl_pct:+.2f}% | Duration: {h.duration_minutes or 0}m"
            )
            tg_close = (
                f"{'🏆' if won else '🛑'} *{'Target Hit' if won else 'Stop Loss'}: {asset.symbol}*\n"
                f"{h.signal_type} closed @ `{h.exit_price:.4f}` | P&L: `{h.pnl_pct:+.2f}%` | {h.duration_minutes or 0}m"
            )
            for user in users:
                key = (user.id, "signal_closed", asset.symbol)
                if key in already_sent:
                    continue
                already_sent.add(key)
                new_notifs.append(Notification(
                    user_id=user.id, title=title, message=msg,
                    notification_type="signal_closed", channel="web",
                    asset_symbol=asset.symbol,
                ))
                try:
                    from app.websocket.events import broadcast_notification
                    broadcast_notification(user.id, title, msg)
                except Exception:
                    pass
                if user.telegram_enabled and user.telegram_chat_id:
                    _send_telegram(user.telegram_chat_id, tg_close)
                if user.push_enabled and user.push_subscription:
                    try:
                        from app.services.push import send_push_to_user
                        send_push_to_user(user, title, msg, url="/dashboard")
                    except Exception:
                        pass

        if new_notifs:
            db.session.add_all(new_notifs)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def send_daily_summary(app):
    """Send a daily Telegram summary at 08:00 UTC to all opted-in users."""
    with app.app_context():
        from app.models.signal import Signal, SignalHistory
        from app.models.user import User
        from app.models.asset import Asset
        from datetime import datetime, timedelta

        yesterday = datetime.utcnow() - timedelta(hours=24)

        # Yesterday's closed signals
        closes = SignalHistory.query.filter(SignalHistory.closed_at >= yesterday).all()
        wins   = [h for h in closes if h.outcome == "win"]
        losses = [h for h in closes if h.outcome == "loss"]
        total  = len(wins) + len(losses)
        win_rate = (len(wins) / total * 100) if total else 0

        # Still-active signals right now
        active = Signal.query.filter_by(status="active").count()

        # New signals in the last 24h
        new_count = Signal.query.filter(Signal.generated_at >= yesterday).count()

        text = (
            "📊 *SmartTrade AI — Daily Summary*\n"
            f"📅 {datetime.utcnow().strftime('%Y-%m-%d')} (last 24h)\n\n"
            f"✅ Wins: `{len(wins)}` | ❌ Losses: `{len(losses)}` | Win Rate: `{win_rate:.1f}%`\n"
            f"🆕 New Signals: `{new_count}` | 🔵 Active Now: `{active}`\n"
        )

        if closes:
            top = sorted(closes, key=lambda h: abs(h.pnl_pct or 0), reverse=True)[:3]
            lines = []
            for h in top:
                icon  = "✅" if h.outcome == "win" else "❌"
                asset = Asset.query.get(h.asset_id)
                sym   = asset.symbol if asset else "?"
                lines.append(f"  {icon} {sym} {h.signal_type} {h.pnl_pct:+.2f}%")
            text += "\n🔝 Top moves:\n" + "\n".join(lines)

        for user in User.query.filter_by(is_active=True, telegram_enabled=True).all():
            if user.telegram_chat_id:
                _send_telegram(user.telegram_chat_id, text)


def register_notification_jobs(scheduler, app):
    scheduler.add_job(send_pending_notifications, "interval", seconds=30,
                      args=[app], id="send_notifications", replace_existing=True)
    scheduler.add_job(fire_signal_alerts, "interval", minutes=5,
                      args=[app], id="signal_alerts", replace_existing=True)
    # Daily summary at 08:00 UTC
    scheduler.add_job(send_daily_summary, "cron", hour=8, minute=0,
                      args=[app], id="daily_summary", replace_existing=True)
    logger.info("Notification jobs registered")
