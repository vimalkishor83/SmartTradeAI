"""
Protective order (feature 1 of this session's build) breach-detection and
trailing-stop logic — the core decision logic for whether/when to close a
real position. Uses a lightweight stand-in object instead of a real
ProtectiveOrder/DB row since these functions only read/write a few
attributes.
"""
from types import SimpleNamespace

from app.tasks.protective_order_tasks import _check_breach, _update_trailing


def _order(side="long", stop_loss=None, take_profit=None,
           trailing_enabled=False, trailing_distance_pct=None, high_water_mark=None):
    return SimpleNamespace(
        side=side, stop_loss=stop_loss, take_profit=take_profit,
        trailing_enabled=trailing_enabled, trailing_distance_pct=trailing_distance_pct,
        high_water_mark=high_water_mark,
    )


class TestStopLossBreach:
    def test_long_breaches_when_price_falls_to_or_below_stop(self):
        order = _order(side="long", stop_loss=95)
        assert _check_breach(order, 95) == "triggered_sl"
        assert _check_breach(order, 90) == "triggered_sl"

    def test_long_does_not_breach_above_stop(self):
        order = _order(side="long", stop_loss=95)
        assert _check_breach(order, 96) is None

    def test_short_breaches_when_price_rises_to_or_above_stop(self):
        order = _order(side="short", stop_loss=105)
        assert _check_breach(order, 105) == "triggered_sl"
        assert _check_breach(order, 110) == "triggered_sl"

    def test_short_does_not_breach_below_stop(self):
        order = _order(side="short", stop_loss=105)
        assert _check_breach(order, 104) is None


class TestTakeProfitBreach:
    def test_long_breaches_when_price_rises_to_or_above_target(self):
        order = _order(side="long", take_profit=110)
        assert _check_breach(order, 110) == "triggered_tp"
        assert _check_breach(order, 115) == "triggered_tp"

    def test_short_breaches_when_price_falls_to_or_below_target(self):
        order = _order(side="short", take_profit=90)
        assert _check_breach(order, 90) == "triggered_tp"
        assert _check_breach(order, 85) == "triggered_tp"

    def test_no_levels_set_never_breaches(self):
        order = _order(side="long")
        assert _check_breach(order, 50) is None
        assert _check_breach(order, 1000) is None


class TestStopLossTakesPriorityOverTakeProfit:
    def test_sl_checked_before_tp_when_both_could_fire(self):
        # Contrived: SL above TP for a long (invalid real-world setup, but
        # verifies the function's own ordering rather than crashing).
        order = _order(side="long", stop_loss=95, take_profit=90)
        # price=90 breaches SL (>=... no, 90 <= 95 is True) — SL wins
        assert _check_breach(order, 90) == "triggered_sl"


class TestTrailingStop:
    def test_long_trailing_breach_below_trail_distance(self):
        order = _order(side="long", trailing_enabled=True, trailing_distance_pct=2.0, high_water_mark=100)
        # trail stop = 100 * (1 - 0.02) = 98
        assert _check_breach(order, 98) == "triggered_trailing"
        assert _check_breach(order, 99) is None

    def test_short_trailing_breach_above_trail_distance(self):
        order = _order(side="short", trailing_enabled=True, trailing_distance_pct=2.0, high_water_mark=100)
        # trail stop = 100 * (1 + 0.02) = 102
        assert _check_breach(order, 102) == "triggered_trailing"
        assert _check_breach(order, 101) is None

    def test_trailing_disabled_ignores_high_water_mark(self):
        order = _order(side="long", trailing_enabled=False, trailing_distance_pct=2.0, high_water_mark=100)
        assert _check_breach(order, 50) is None  # would breach trailing if enabled, but it's not


class TestUpdateTrailing:
    def test_long_ratchets_up_only(self):
        order = _order(side="long", high_water_mark=100)
        _update_trailing(order, 110)
        assert order.high_water_mark == 110
        _update_trailing(order, 105)  # price drops — must NOT lower the mark
        assert order.high_water_mark == 110

    def test_short_ratchets_down_only(self):
        order = _order(side="short", high_water_mark=100)
        _update_trailing(order, 90)
        assert order.high_water_mark == 90
        _update_trailing(order, 95)  # price rises — must NOT raise the mark back
        assert order.high_water_mark == 90

    def test_none_high_water_mark_initializes_to_current_price(self):
        order = _order(side="long", high_water_mark=None)
        _update_trailing(order, 100)
        assert order.high_water_mark == 100
