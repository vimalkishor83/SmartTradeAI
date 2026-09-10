"""Shared trade-level validation and milestone tracking.

The Terminal and persisted signal workers must use the same directional
contract. A short is protected above entry and takes profit below entry; a
long is the reverse. Milestones are append-only so the UI can explain what
actually happened without reconstructing events from the current price.
"""

from datetime import datetime
import math


def validate_trade_levels(direction, entry, stop_loss, target1, target2, target3):
    """Return a stable validation result for actionable trade levels."""
    values = (entry, stop_loss, target1, target2, target3)
    if direction not in ("BUY", "SELL") or any(
        value is None or not math.isfinite(float(value)) or float(value) <= 0
        for value in values
    ):
        return {"valid": False, "reason": "missing_or_invalid_level"}

    entry, stop_loss, target1, target2, target3 = map(float, values)
    if direction == "BUY":
        valid = stop_loss < entry < target1 < target2 < target3
    else:
        valid = target3 < target2 < target1 < entry < stop_loss

    return {
        "valid": valid,
        "reason": None if valid else "levels_do_not_match_direction",
    }


def initial_event_history(generated_at=None, entry_price=None):
    """Create the only event we can know at signal creation time."""
    at = generated_at or datetime.utcnow()
    return [{
        "type": "generated",
        "at": at.isoformat() if hasattr(at, "isoformat") else str(at),
        "price": float(entry_price) if entry_price is not None else None,
    }]


def reconcile_trailing_milestones(history, trail_stage, target1, target2, target3):
    """Restore target events implied by a previously saved trailing stage.

    Older live-read rows stored the trailing stage before event history was
    introduced. We can restore which targets were reached, but not invent
    their historical timestamps, so those events are explicitly marked with
    ``time_unknown`` for the UI.
    """
    events = [event for event in (history or []) if isinstance(event, dict) and event.get("type")]
    try:
        stage = max(0, min(3, int(trail_stage or 0)))
    except (TypeError, ValueError):
        stage = 0

    targets = (("target1", target1), ("target2", target2), ("target3", target3))
    seen = {event.get("type") for event in events}
    changed = False
    for index, (event_type, level) in enumerate(targets, start=1):
        if index > stage or event_type in seen or level is None:
            continue
        try:
            level = float(level)
        except (TypeError, ValueError):
            continue
        events.append({"type": event_type, "at": None, "price": level, "time_unknown": True})
        seen.add(event_type)
        changed = True
    return events, changed


def record_milestones(
    history,
    direction,
    current_price,
    entry_price,
    stop_loss,
    target1,
    target2,
    target3,
    generated_at=None,
    include_stop=False,
    now=None,
):
    """Append first-observed target/stop events and return ``(events, changed)``.

    The caller decides whether the stop is terminal because a live preview may
    use a tightened trailing stop, while a persisted signal uses its initial
    stop. Targets are recorded in order, including crossed levels on a price
    jump. Existing events are never replaced.
    """
    try:
        price = float(current_price)
    except (TypeError, ValueError):
        return list(history or []), False
    if direction not in ("BUY", "SELL") or not math.isfinite(price):
        return list(history or []), False

    events = [event for event in (history or []) if isinstance(event, dict) and event.get("type")]
    if not any(event.get("type") == "generated" for event in events):
        events.insert(0, initial_event_history(generated_at, entry_price)[0])

    seen = {event.get("type") for event in events}
    at = now or datetime.utcnow()
    at_value = at.isoformat() if hasattr(at, "isoformat") else str(at)
    changed = False

    targets = (("target1", target1), ("target2", target2), ("target3", target3))
    for event_type, level in targets:
        if event_type in seen or level is None:
            continue
        try:
            level = float(level)
        except (TypeError, ValueError):
            continue
        reached = price >= level if direction == "BUY" else price <= level
        if reached:
            events.append({"type": event_type, "at": at_value, "price": level})
            seen.add(event_type)
            changed = True

    if include_stop and "stop_loss" not in seen and stop_loss is not None:
        try:
            stop_loss = float(stop_loss)
        except (TypeError, ValueError):
            stop_loss = None
        reached = (
            stop_loss is not None
            and (price <= stop_loss if direction == "BUY" else price >= stop_loss)
        )
        if reached:
            events.append({"type": "stop_loss", "at": at_value, "price": price})
            changed = True

    return events, changed
