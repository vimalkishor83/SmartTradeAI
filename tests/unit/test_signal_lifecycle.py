from datetime import datetime

from app.services.signals.lifecycle import (
    initial_event_history,
    record_milestones,
    validate_trade_levels,
)


def test_directional_levels_require_stop_on_the_loss_side():
    assert validate_trade_levels("BUY", 100, 95, 105, 110, 115)["valid"]
    assert validate_trade_levels("SELL", 100, 105, 95, 90, 85)["valid"]
    assert not validate_trade_levels("SELL", 100, 95, 95, 90, 85)["valid"]
    assert not validate_trade_levels("BUY", 100, 105, 110, 115, 120)["valid"]


def test_milestones_are_append_only_and_record_crossed_sell_targets():
    generated = datetime(2026, 9, 10, 10, 0)
    events, changed = record_milestones(
        initial_event_history(generated, 100), "SELL", 84, 100, 105,
        95, 90, 85, generated_at=generated,
    )

    assert changed
    assert [event["type"] for event in events] == [
        "generated", "target1", "target2", "target3",
    ]

    again, changed_again = record_milestones(
        events, "SELL", 83, 100, 105, 95, 90, 85,
        generated_at=generated,
    )
    assert not changed_again
    assert again == events


def test_stop_event_uses_the_effective_trailing_stop():
    events, changed = record_milestones(
        initial_event_history(datetime(2026, 9, 10, 10, 0), 100),
        "SELL", 103, 100, 102, 95, 90, 85, include_stop=True,
    )

    assert changed
    assert events[-1]["type"] == "stop_loss"
    assert events[-1]["price"] == 103
