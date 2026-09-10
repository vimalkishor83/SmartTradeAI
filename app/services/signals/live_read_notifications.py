"""Telegram notifications for Terminal live-read lifecycle events."""

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db


def _telegram_disclaimer():
    # Keep Terminal lifecycle alerts consistent with regular signal alerts:
    # two newlines separate the context footer and the link remains clickable.
    from app.tasks.notification_tasks import _TELEGRAM_DISCLAIMER

    return _TELEGRAM_DISCLAIMER


def _event_identity(event):
    event_type = str(event.get("type") or "")
    stage = event.get("stage") if event_type == "trailing_stop" else ""
    return event_type, str(stage or "")


def _new_events(events, previous_events):
    previous = {_event_identity(event) for event in (previous_events or []) if isinstance(event, dict)}
    return [
        event for event in (events or [])
        if isinstance(event, dict) and event.get("type") and _event_identity(event) not in previous
    ]


def _price(value):
    try:
        text = f"{float(value):.8f}".rstrip("0").rstrip(".")
        return text or "0"
    except (TypeError, ValueError):
        return "—"


def _market_enabled(cfg, market):
    return market in (cfg.get("telegram_signal_individual_markets") or [])


def _telegram_ready(user):
    if not user.telegram_enabled or not user.telegram_chat_id:
        return False
    try:
        token = user.get_telegram_bot_token() or current_app.config.get("TELEGRAM_BOT_TOKEN")
    except Exception:
        token = current_app.config.get("TELEGRAM_BOT_TOKEN")
    return bool(token)


def _reasoning_lines(row):
    reasons = row.reasoning_detail or []
    if reasons:
        ordered = sorted(
            reasons,
            key=lambda item: not (item.get("aligned", True) if isinstance(item, dict) else True),
        )
        return [
            item.get("text") if isinstance(item, dict) else str(item)
            for item in ordered[:4]
            if (item.get("text") if isinstance(item, dict) else str(item))
        ]
    return [row.reasoning] if row.reasoning else []


def format_live_read_event(row, event):
    """Return a detailed, user-facing Telegram message for one event."""
    asset = row.asset
    symbol = asset.symbol if asset else "Unknown asset"
    direction = row.signal_type or "SIGNAL"
    event_type = event.get("type")
    stage = int(event.get("stage") or row.trail_stage or 0)
    price = event.get("price")
    if event_type == "generated":
        title = f"{'🟢' if direction == 'BUY' else '🔴'} *LIVE {direction} SIGNAL — {symbol}*"
        lines = [
            title,
            "",
            f"Timeframe: `{row.timeframe}`",
            f"Entry: `{_price(row.entry_price)}`",
            f"Initial stop loss: `{_price(row.stop_loss)}`",
            f"Target 1: `{_price(row.target1)}`",
            f"Target 2: `{_price(row.target2)}`",
            f"Target 3: `{_price(row.target3)}`",
        ]
        if row.confidence_score is not None:
            lines.append(f"Confidence: `{float(row.confidence_score):.0f}%`")
        if row.snapshot and row.snapshot.get("risk_reward") is not None:
            lines.append(f"R:R: `1:{float(row.snapshot['risk_reward']):.1f}`")
        reasons = _reasoning_lines(row)
        if reasons:
            lines.extend(["", "*Why this signal:*", *[f"• {reason}" for reason in reasons]])
        lines.extend(["", "Entry and levels remain fixed until a final target or effective stop is reached."])
    elif event_type in ("target1", "target2", "target3"):
        target_number = event_type[-1]
        title = f"🎯 *TARGET {target_number} HIT — {symbol}*"
        lines = [
            title,
            "",
            f"{direction} · Timeframe: `{row.timeframe}`",
            f"Entry: `{_price(row.entry_price)}`",
            f"Target {target_number}: `{_price(price)}`",
        ]
        if row.trailing_stop is not None:
            lines.append(f"Active stop: `{_price(row.trailing_stop)}`")
        if event_type != "target3":
            lines.append(f"Next target: `{_price(getattr(row, f'target{int(target_number) + 1}', None))}`")
        else:
            lines.append("Lifecycle: `Final target reached`")
    elif event_type == "trailing_stop":
        title = f"🛡️ *TRAILING STOP ACTIVATED — {symbol}*"
        lines = [
            title,
            "",
            f"{direction} · Timeframe: `{row.timeframe}`",
            f"After Target {stage}",
            f"Active stop: `{_price(price)}`",
            f"Initial stop: `{_price(row.stop_loss)}`",
        ]
    elif event_type == "stop_loss":
        title = f"🛑 *STOP LOSS HIT — {symbol}*"
        lines = [
            title,
            "",
            f"{direction} · Timeframe: `{row.timeframe}`",
            f"Entry: `{_price(row.entry_price)}`",
            f"Exit price: `{_price(price)}`",
            f"Initial stop: `{_price(row.stop_loss)}`",
        ]
        if row.trailing_stop is not None:
            lines.append(f"Effective trailing stop: `{_price(row.trailing_stop)}`")
    else:
        return ""

    return "\n".join(line for line in lines if line != "") + _telegram_disclaimer()


def enqueue_live_read_event_notifications(row, events, previous_events):
    """Queue one Telegram notification per opted-in user and event.

    The notification key makes this safe when a Terminal request and the
    background tracker observe the same milestone close together. A nested
    savepoint lets a concurrent duplicate lose cleanly without rolling back
    the live-read state update around it.
    """
    asset = row.asset
    if not asset:
        return 0

    from app.models.notification import Notification
    from app.models.user import User
    from app.services.platform_config import get_platform_config
    from app.services.notifications.telegram_individual_signal_limits import individual_signal_allowed

    if (not _market_enabled(get_platform_config(), asset.market)
            or not individual_signal_allowed(asset.id, row.timeframe)):
        return 0

    new_events = _new_events(events, previous_events)
    if not new_events:
        return 0

    users = User.query.filter_by(is_active=True, telegram_enabled=True).all()
    queued = 0
    for event in new_events:
        text = format_live_read_event(row, event)
        if not text:
            continue
        title_line, _, body = text.partition("\n")
        title = title_line.replace("*", "").strip()
        event_type, stage = _event_identity(event)
        key = f"terminal-live:{row.id}:{event_type}:{stage}"
        for user in users:
            if not _telegram_ready(user):
                continue
            exists = Notification.query.filter_by(
                user_id=user.id, notification_key=key,
            ).first()
            if exists:
                continue
            try:
                with db.session.begin_nested():
                    db.session.add(Notification(
                        user_id=user.id,
                        title=title,
                        message=body.lstrip(),
                        notification_type="terminal_signal_event",
                        channel="telegram",
                        asset_symbol=asset.symbol,
                        notification_key=key,
                    ))
                    db.session.flush()
                queued += 1
            except IntegrityError:
                # A unique-key race means another worker already queued it.
                # Other database errors are left for the outer transaction to
                # handle, while this event remains observable on the card.
                continue
    return queued
