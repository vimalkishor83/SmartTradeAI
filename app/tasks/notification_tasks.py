"""Background jobs for sending notifications."""
import logging

logger = logging.getLogger(__name__)

def _market_enabled(cfg: dict, field: str, market: str) -> bool:
    """Per-category, per-delivery-level market list (e.g.
    telegram_signal_group_markets) — the opposite convention from
    TelegramAlertChannel.markets: here an EMPTY list means off for every
    market, not "every market", since these fields exist specifically to
    let an admin say "crypto signal alerts go to individuals and a group,
    forex signal alerts go to the group only, gold gets neither" from one
    page, and that only works if leaving a market unchecked actually
    means "not this one" rather than needing every market explicitly
    disabled elsewhere first."""
    return market in (cfg.get(field) or [])


# Appended to every trade-related Telegram message (new signal, close,
# watchlist, protective order) — Telegram's legacy Markdown parse_mode
# supports [text](url) links same as MarkdownV2 does.
_TELEGRAM_DISCLAIMER = (
    "\n\n⚠️ _Disclaimer: For informational purposes only — not financial "
    "advice. [Read full disclaimer](https://smarttradeai.online/disclaimer)_"
)


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

            # Claim BEFORE sending, not after. This loop previously sent first
            # and only flipped is_sent at the end of the whole batch, so two
            # overlapping runs of this job — which happens by design the moment
            # more than one process registers it, and can also happen on a slow
            # batch — would both read the same is_sent=False row and both send
            # the email/Telegram. Mirrors _claim_signal_close() in
            # data_tasks.py: a conditional UPDATE whose rowcount tells us
            # whether we won the race.
            if not _claim_notification(notif):
                continue

            try:
                if user.email_notifications and notif.channel in ("email", None):
                    _send_email(user.email, notif.title, notif.message)
                # channel="web" notifications (signal/watchlist/protective-order/
                # trial/upgrade alerts) are created purely for the in-app bell —
                # every one of those already sends its own richly-formatted
                # Telegram message (with disclaimer + reasoning) directly from
                # its own task the moment it fires. Without this channel check,
                # this 30s sweep picked up the exact same row again the moment
                # it saw is_sent=False and re-sent it as a second, bare
                # "*title*\nmessage" Telegram message with no disclaimer and no
                # reasoning bullets — the duplicate/disclaimer-missing alerts
                # reported in production were this second, unwanted send.
                if user.telegram_enabled and user.telegram_chat_id and notif.channel in ("telegram", None):
                    _send_telegram(user, f"*{notif.title}*\n{notif.message}")
            except Exception as e:
                # Release the claim so a later run retries rather than silently
                # dropping the notification — claiming up front must not turn a
                # transient SMTP/Telegram failure into permanent loss.
                logger.error(f"Notification send failed: {e}")
                db.session.execute(
                    Notification.__table__.update()
                    .where(Notification.id == notif.id)
                    .values(is_sent=False, sent_at=None)
                )
                db.session.commit()

        db.session.commit()


def _claim_notification(notif) -> bool:
    """Atomically claim one pending notification for sending.

    Returns True only if THIS caller flipped is_sent False->True, i.e. won the
    race against any concurrently-running copy of send_pending_notifications.
    A loser gets rowcount 0 and skips the send, which is what prevents the
    duplicate email/Telegram spam that a plain read-then-mutate allowed.
    """
    from app.models.notification import Notification
    from app.extensions import db
    from datetime import datetime

    result = db.session.execute(
        Notification.__table__.update()
        .where(Notification.id == notif.id, Notification.is_sent == False)  # noqa: E712
        .values(is_sent=True, sent_at=datetime.utcnow())
    )
    db.session.commit()
    return result.rowcount > 0


def _send_email(to_email: str, subject: str, body: str):
    # Routed through the shared mailer service (Flask-Mail) so this respects
    # MAIL_SUPPRESS_SEND the same way verification/reset emails do — this
    # previously duplicated its own raw smtplib connection with no
    # suppression, so every deploy without SMTP creds configured logged a
    # noisy "Email send error" on every single pending notification.
    from app.services.mailer import send_email
    send_email(to_email, subject, body)


def _telegram_token_for(user) -> str | None:
    """Each user's own bot token first — not one shared TELEGRAM_BOT_TOKEN
    for everyone — falling back to the platform's bot only if the user
    hasn't set their own. Mirrors _resolve_telegram_token in auth/routes.py
    (kept separate: that one also takes a live request-body override for
    the Settings-page test button, which doesn't apply to a background job)."""
    from flask import current_app
    token = user.get_telegram_bot_token()
    return token or current_app.config.get("TELEGRAM_BOT_TOKEN")


def _send_telegram(user, text: str):
    try:
        import requests
        token = _telegram_token_for(user)
        if not token or not user.telegram_chat_id:
            # telegram_enabled=True with no token/chat_id yet is a normal,
            # common in-progress setup state (the Settings page's own "Find
            # my Chat ID" step requires messaging the bot first) — but it
            # was previously indistinguishable from every alert silently
            # never arriving. One clear line per user per run is cheap and
            # shows up in the admin System Logs viewer, unlike the request-
            # scoped logger this file otherwise uses.
            logger.warning(
                f"Telegram alert skipped for user {user.id} ({user.username}): "
                f"{'no bot token configured' if not token else 'no chat_id saved yet'}"
            )
            return
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": user.telegram_chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
        # A rejected message (bad token, wrong/blocked chat_id, bot removed
        # from the chat) comes back as a normal 400/403 JSON body, not a
        # network exception — requests never raises for that on its own,
        # so this previously "succeeded" from this function's point of view
        # no matter what Telegram actually did with it.
        if not resp.ok:
            logger.warning(
                f"Telegram alert rejected for user {user.id} ({user.username}): "
                f"HTTP {resp.status_code} — {resp.text[:200]}"
            )
    except Exception as e:
        # user is sometimes not the User object the type hint promises (seen
        # live: "'str' object has no attribute 'get_telegram_bot_token'") —
        # every current call site does pass a real User, so logging what
        # actually arrived here is the fastest way to catch whichever one
        # doesn't the next time this fires, rather than re-auditing every
        # call site by eye again.
        logger.error(f"Telegram send error: {e} (user was {type(user).__name__}: {user!r})")


def send_new_ip_login_alert(logged_in_user, ip: str, user_agent: str):
    """Security notification for super admins only — never sent to the
    logged-in user's own personal Telegram alerts, and not organized into
    the trading Individual/Group channel system at all (this isn't a
    market-scoped alert, so neither concept applies). Called from
    /auth/login the moment a login is confirmed to be this account's
    first time seeing this IP (not its first login ever — see the caller
    for that distinction). Delivered on every channel a given admin has:
    always as a bell-icon Notification + live WebSocket push, plus their
    personal Telegram chat when linked (using the PLATFORM bot token — a
    super admin who hasn't linked their own bot still gets these via the
    shared TELEGRAM_BOT_TOKEN fallback in _telegram_token_for) and browser
    push when subscribed — so an admin without Telegram configured still
    sees this in-app instead of missing a security alert entirely.
    """
    try:
        from datetime import datetime
        from app.extensions import db
        from app.models.user import User
        from app.models.notification import Notification
        from app.models.user_session import parse_device_label

        # Every active super admin gets the bell/push notification regardless
        # of their Telegram setup — Telegram is one more channel on top, not
        # the only one, so an admin who hasn't linked Telegram still sees
        # this in-app instead of missing it entirely.
        admins = User.query.filter_by(is_super_admin=True, is_active=True).all()
        if not admins:
            return

        device = parse_device_label(user_agent)
        when = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
        title = "🔐 New IP Login"
        body = (
            f"{logged_in_user.username} ({logged_in_user.full_name}) logged in from a "
            f"new IP {ip} on {device} at {when}. This IP hasn't been seen for this account before."
        )
        text = (
            f"🔐 *NEW IP LOGIN*\n\n"
            f"👤 User: `{logged_in_user.username}` ({logged_in_user.full_name})\n"
            f"📧 Email: `{logged_in_user.email}`\n"
            f"🌐 IP: `{ip}`\n"
            f"💻 Device: {device}\n"
            f"🕐 Time: `{when}`\n\n"
            f"_This IP hasn't been seen for this account before._"
        )
        for admin in admins:
            db.session.add(Notification(
                user_id=admin.id, title=title, message=body,
                notification_type="security_alert", channel="web",
            ))
            try:
                from app.websocket.events import broadcast_notification
                broadcast_notification(admin.id, title, body)
            except Exception:
                pass
            if admin.telegram_enabled and admin.telegram_chat_id:
                _send_telegram(admin, text)
            if admin.push_enabled and admin.push_subscription:
                try:
                    from app.services.push import send_push_to_user
                    send_push_to_user(admin, title, body, url="/admin/security")
                except Exception:
                    pass
        db.session.commit()
    except Exception as e:
        logger.error(f"New-IP-login alert failed: {e}")


def _send_to_chat(chat_id: str, text: str):
    """Broadcasts one message to an arbitrary Telegram chat/group id using
    the shared platform bot (TELEGRAM_BOT_TOKEN) — a group chat isn't any
    individual user's own account, so this never falls back to a per-user
    bot token the way _send_telegram does. No-ops silently if the bot
    token isn't configured yet."""
    try:
        from flask import current_app
        token = current_app.config.get("TELEGRAM_BOT_TOKEN")
        if not token or not chat_id:
            return

        import requests
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=5,
        )
        if not resp.ok:
            logger.warning(f"Telegram group broadcast rejected (chat {chat_id}): HTTP {resp.status_code} — {resp.text[:200]}")
    except Exception as e:
        logger.error(f"Telegram group broadcast error (chat {chat_id}): {e}")


def send_security_alert(text: str):
    """Sends one message to the dedicated security-notifications Telegram
    group (PlatformConfig.telegram_security_chat_id), using the shared
    platform bot — same delivery mechanism as the trading-signal group
    channels (_send_to_chat), just a different chat and a different
    purpose (login activity, unauthorized admin access, anonymous
    visits — never trading signals). No-ops silently if no chat id has
    been configured yet. Callers check their own specific
    telegram_security_notify_* toggle before calling this; this function
    only handles delivery, not which events are enabled."""
    try:
        from app.services.platform_config import get_platform_config
        chat_id = get_platform_config().get("telegram_security_chat_id")
        if not chat_id:
            return
        _send_to_chat(chat_id, text)
    except Exception as e:
        logger.error(f"Security alert broadcast failed: {e}")


def _send_to_channels(text: str, market: str, category: str, timeframe: str | None = None):
    """Fans one alert out to every active TelegramAlertChannel whose own
    market list, timeframe list, and category toggle all match — e.g. a
    "Crypto Scalpers" channel scoped to market="crypto",
    timeframes=["1m","5m"] with alerts_signal=True only gets crypto
    BUY/SELL signals on those two timeframes, while a "Swing" channel on
    ["4h","1d"] never sees them. Replaces the old single global group
    destination: different markets/timeframes legitimately want different
    audiences and different alert mixes."""
    try:
        from app.models.telegram_alert_channel import TelegramAlertChannel
        channels = TelegramAlertChannel.query.filter_by(is_active=True).all()
        for channel in channels:
            if channel.matches(market, category, timeframe):
                _send_to_chat(channel.group_chat_id, text)
    except Exception as e:
        logger.error(f"Telegram channel fan-out error: {e}")


# ── MTF rating-change alerts (Delta Scanner / MTF Analysis) ─────────────────
# EMA 9/21 MTF's own 5-point scale (app/services/indicators/ema_mtf.py) —
# ordered weakest-to-strongest so "upgraded/downgraded" and "which zone" are
# both just index/lookup comparisons, not a pile of if/elif.
_RATING_ORDER = ["Strong Sell", "Sell", "Neutral", "Buy", "Strong Buy"]
_RATING_ZONE = {
    "Strong Sell": "sell", "Sell": "sell",
    "Neutral": "neutral",
    "Buy": "buy", "Strong Buy": "buy",
}


def _is_ratingchange_alertworthy(old_rating: str, new_rating: str, sensitivity: str) -> bool:
    """Admin-configured (Platform Config -> Telegram Group Alerts) so a
    quiet market's constant Buy<->Strong Buy flicker doesn't have to mean
    either "alert on everything" or "alert on nothing" for the whole
    feature — the admin picks where that line sits."""
    if old_rating == new_rating:
        return False
    if sensitivity == "every_change":
        return True
    if sensitivity == "extremes_only":
        return new_rating in ("Strong Buy", "Strong Sell")
    # "cross_zone" (default): only alert when the zone itself changes
    # (sell/neutral/buy) — Sell -> Strong Sell is the same call getting more
    # confident, not a new call; Neutral -> Buy or Sell -> Neutral are.
    return _RATING_ZONE.get(old_rating) != _RATING_ZONE.get(new_rating)


def _overall_trend_text(tf_cells: dict) -> str:
    """Majority-vote summary across this asset's other computed timeframes
    — "is the bigger picture actually bullish, or is this one timeframe
    flipping against the grain" is exactly what turns a raw rating change
    into something a subscriber can act on."""
    ratings = [c["rating"] for c in tf_cells.values() if c and c.get("rating")]
    if not ratings:
        return "Not enough data"
    zones = [_RATING_ZONE.get(r, "neutral") for r in ratings]
    buy_n, sell_n, total = zones.count("buy"), zones.count("sell"), len(zones)
    if buy_n > total / 2:
        return f"Bullish ({buy_n}/{total} timeframes)"
    if sell_n > total / 2:
        return f"Bearish ({sell_n}/{total} timeframes)"
    return f"Mixed ({buy_n} buy · {sell_n} sell · {total - buy_n - sell_n} neutral)"


def _format_rating_change_telegram(symbol: str, tf: str, old_rating: str, new_rating: str,
                                    reason: str, overall_trend: str) -> str:
    upgraded = _RATING_ORDER.index(new_rating) > _RATING_ORDER.index(old_rating)
    icon = "🟢" if _RATING_ZONE[new_rating] == "buy" else "🔴" if _RATING_ZONE[new_rating] == "sell" else "⚪"
    lines = [
        f"{icon} *MTF RATING CHANGE — {symbol}* (`{tf}`)",
        "",
        f"{'⬆️' if upgraded else '⬇️'} `{old_rating}` → *{new_rating}*",
    ]
    if reason:
        lines.append("")
        lines.append(f"_{reason}_")
    lines.append("")
    lines.append(f"📊 Overall trend: *{overall_trend}*")
    return "\n".join(lines) + _TELEGRAM_DISCLAIMER


def check_rating_changes(app):
    """Compares each asset+timeframe's just-computed EMA 9/21 MTF rating
    (app/services/indicators/ema_mtf.py) against its last-known value and
    alerts on a meaningful shift, per the admin's configured sensitivity —
    e.g. an asset moving from Sell to Buy on the 1h, with the reasoning
    behind it and how the other timeframes for that asset currently read.

    Called from prewarm_ta_cache right after it computes ema_rows for its
    own cache — reuses that computation instead of running it a second
    time, since this only needs to run on the same 5-minute cadence
    anyway."""
    with app.app_context():
        from app.extensions import cache, db
        from app.models.rating_snapshot import RatingSnapshot
        from app.models.user import User
        from app.services.platform_config import get_platform_config

        cfg = get_platform_config()
        # Fast bail-out only when NO market is enabled for EITHER delivery
        # level — the actual per-market decision happens per-row below.
        if not cfg.get("telegram_rating_change_individual_markets") and not cfg.get("telegram_rating_change_group_markets"):
            return
        sensitivity = cfg.get("telegram_rating_change_sensitivity", "cross_zone")

        cached = cache.get("ema_summary_all")
        ema_rows = (cached or {}).get("assets") or []
        if not ema_rows:
            return

        existing = {(s.asset_id, s.timeframe): s for s in RatingSnapshot.query.all()}
        users = None  # lazy — only fetched if something actually needs sending

        for row in ema_rows:
            market = row.get("market")
            individual_on = _market_enabled(cfg, "telegram_rating_change_individual_markets", market)
            group_on = _market_enabled(cfg, "telegram_rating_change_group_markets", market)
            tf_cells = row.get("tf") or {}
            for tf, cell in tf_cells.items():
                if not cell or not cell.get("rating"):
                    continue
                new_rating = cell["rating"]
                snap = existing.get((row["id"], tf))
                old_rating = snap.rating if snap else None

                # Snapshot tracking always runs, even for a market currently
                # filtered out of alerts — otherwise re-enabling a market
                # later compares against a stale rating from before it was
                # disabled and could fire a misleading "change" for a shift
                # that actually happened gradually while muted.
                if old_rating and (individual_on or group_on) and _is_ratingchange_alertworthy(old_rating, new_rating, sensitivity):
                    overall = _overall_trend_text(tf_cells)
                    text = _format_rating_change_telegram(
                        row["symbol"], tf, old_rating, new_rating, cell.get("reason", ""), overall
                    )
                    if group_on:
                        _send_to_channels(text, market, "rating_change", tf)
                    if individual_on:
                        if users is None:
                            users = User.query.filter_by(is_active=True, telegram_enabled=True).all()
                        for user in users:
                            if user.telegram_chat_id:
                                _send_telegram(user, text)

                if snap:
                    snap.rating = new_rating
                else:
                    db.session.add(RatingSnapshot(asset_id=row["id"], timeframe=tf, rating=new_rating))

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Rating snapshot commit failed: {e}")


def _format_signal_telegram(sig, asset) -> str:
    """Full-detail Telegram message for a new signal — entry, stop loss,
    all three targets (not just T1), risk:reward, confidence, and the
    actual "why" behind the call as bullet points, pulled from the
    signal's own stored reasoning_detail rather than just a bare number.
    Telegram's Markdown mode has no real text color, so "colorful" here
    means emoji + bold + a consistent structure, not literal font color."""
    is_buy = sig.signal_type == "BUY"
    icon = "🟢" if is_buy else "🔴"

    lines = [f"{icon} *{sig.signal_type} SIGNAL — {asset.symbol}*", ""]
    lines.append(f"📍 Entry: `{sig.entry_price:.4f}`")
    lines.append(f"🛑 Stop Loss: `{sig.stop_loss:.4f}`")
    for n, t in ((1, sig.target1), (2, sig.target2), (3, sig.target3)):
        if t:
            lines.append(f"🎯 Target {n}: `{t:.4f}`")
    meta = [f"TF: `{sig.timeframe}`", f"Confidence: `{sig.confidence_score:.0f}%`"]
    if sig.confidence_label:
        meta[-1] += f" ({sig.confidence_label})"
    if sig.risk_reward:
        meta.insert(0, f"R:R `1:{sig.risk_reward:.1f}`")
    lines.append(" | ".join(meta))

    # reasoning_detail is the structured, per-factor breakdown (see
    # SignalEngine._labeled_reasons) — falls back to the older plain-text
    # "reasoning" field for any signal saved before that existed. Each
    # entry carries `aligned`: whether that factor actually supports the
    # final BUY/SELL call, or was outweighed by a stronger opposing signal
    # (e.g. a reversal pattern beating several trend/momentum tags the
    # other way — same thing the terminal's "Why this signal?" panel
    # strikes through). Sorting aligned-first before truncating to 6
    # matters: raw reasoning_detail order is factor-category order, not
    # relevance order, so a straight reasons[:6] could — and in production
    # did — cut off the actual deciding reasons and send only the
    # contradicted ones instead, e.g. a SELL alert whose "Why" bullets
    # were all bullish trend factors that lost the vote.
    reasons = sig.reasoning_detail or []
    if reasons:
        ordered = sorted(reasons, key=lambda r: not (r.get("aligned", True) if isinstance(r, dict) else True))
        lines.append("")
        lines.append("*Why:*")
        for r in ordered[:6]:
            text = r.get("text") if isinstance(r, dict) else str(r)
            if text:
                lines.append(f"• {text}")
    elif sig.reasoning:
        lines.append("")
        lines.append("*Why:* " + sig.reasoning.replace(" | ", ", "))

    return "\n".join(lines) + _TELEGRAM_DISCLAIMER


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

        from app.services.platform_config import get_platform_config
        cfg = get_platform_config()

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
            tg_msg = _format_signal_telegram(sig, asset)
            tg_individual_allowed = _market_enabled(cfg, "telegram_signal_individual_markets", asset.market)
            tg_group_allowed = _market_enabled(cfg, "telegram_signal_group_markets", asset.market)
            # Once per signal, not once per user — this is a shared group,
            # not an inbox each user gets their own copy of. Guarded the
            # same way per-user sends are: cutoff is a 6-minute lookback on
            # a 5-minute poll, so a signal can legitimately still be "new"
            # on two consecutive runs — checking whether any user already
            # has a logged notification for it is the same signal this
            # already went out for.
            if tg_group_allowed and not any(
                (u.id, "signal_alert", asset.symbol) in already_sent for u in users
            ):
                _send_to_channels(tg_msg, asset.market, "signal", sig.timeframe)
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
                if tg_individual_allowed and user.telegram_enabled and user.telegram_chat_id:
                    _send_telegram(user, tg_msg)
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
            duration = h.duration_minutes or 0
            duration_label = f"{duration // 60}h {duration % 60}m" if duration >= 60 else f"{duration}m"
            tg_close = (
                f"{'🏆' if won else '🛑'} *{'TARGET HIT' if won else 'STOP LOSS'} — {asset.symbol}*\n\n"
                f"{h.signal_type} · TF: `{h.timeframe or '—'}`\n"
                f"📍 Entry: `{h.entry_price:.4f}`\n"
                f"{'🎯' if won else '🛑'} Exit: `{h.exit_price:.4f}`\n"
                f"{'📈' if h.pnl_pct >= 0 else '📉'} P&L: `{h.pnl_pct:+.2f}%` | ⏱ Held: `{duration_label}`"
            ) + _TELEGRAM_DISCLAIMER
            tg_close_individual_allowed = _market_enabled(cfg, "telegram_signal_closed_individual_markets", asset.market)
            tg_close_group_allowed = _market_enabled(cfg, "telegram_signal_closed_group_markets", asset.market)
            if tg_close_group_allowed and not any(
                (u.id, "signal_closed", asset.symbol) in already_sent for u in users
            ):
                _send_to_channels(tg_close, asset.market, "signal_closed", h.timeframe)
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
                if tg_close_individual_allowed and user.telegram_enabled and user.telegram_chat_id:
                    _send_telegram(user, tg_close)
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
                _send_telegram(user, text)


def register_notification_jobs(scheduler, app):
    scheduler.add_job(send_pending_notifications, "interval", seconds=30,
                      args=[app], id="send_notifications", replace_existing=True)
    scheduler.add_job(fire_signal_alerts, "interval", minutes=5,
                      args=[app], id="signal_alerts", replace_existing=True)
    # Daily summary at 08:00 UTC
    scheduler.add_job(send_daily_summary, "cron", hour=8, minute=0,
                      args=[app], id="daily_summary", replace_existing=True)
    logger.info("Notification jobs registered")
