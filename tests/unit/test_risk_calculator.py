"""
Position sizing / risk-reward calculator — pure functions, no I/O. These
numbers feed directly into how much real capital a user risks per trade,
so a regression here (e.g. a units/risk_amount formula error) has direct
financial consequence, making this one of the highest-value places in
the codebase to lock in with tests.
"""
from app.services.risk.calculator import (
    calculate_position,
    calculate_position_volatility,
    calculate_risk_reward,
)


class TestCalculatePosition:
    def test_basic_long_position_sizing(self):
        result = calculate_position(capital=100_000, risk_pct=1, entry=100, stop_loss=95)
        # risk_amount = 100000 * 0.01 = 1000; risk_per_unit = 5; units = 200
        assert result["risk_amount"] == 1000.0
        assert result["risk_per_unit"] == 5.0
        assert result["units"] == 200.0
        assert result["position_value"] == 20000.0
        assert result["max_loss"] == 1000.0

    def test_short_position_uses_absolute_risk_per_unit(self):
        # stop above entry (short) must give the same positive risk_per_unit
        # as a long with the mirrored distance, not a negative number.
        result = calculate_position(capital=100_000, risk_pct=1, entry=100, stop_loss=105)
        assert result["risk_per_unit"] == 5.0
        assert result["units"] == 200.0

    def test_missing_capital_returns_error(self):
        result = calculate_position(capital=0, risk_pct=1, entry=100, stop_loss=95)
        assert "error" in result

    def test_zero_risk_distance_returns_error(self):
        result = calculate_position(capital=100_000, risk_pct=1, entry=100, stop_loss=100)
        assert "error" in result

    def test_lot_size_divides_units_into_lots(self):
        result = calculate_position(capital=100_000, risk_pct=1, entry=100, stop_loss=95, lot_size=50)
        assert result["units"] == 200.0
        assert result["lots"] == 4.0

    def test_margin_required_is_ten_percent_of_position_value(self):
        result = calculate_position(capital=100_000, risk_pct=1, entry=100, stop_loss=95)
        assert result["margin_required"] == round(result["position_value"] * 0.1, 2)


class TestCalculatePositionVolatility:
    def test_normal_regime_at_low_atr_percentile(self):
        # atr sits below every value in the lookback window -> percentile 0 -> normal/1.0x
        result = calculate_position_volatility(
            capital=100_000, risk_pct=1, entry=100, stop_loss=95, atr=1.0,
            atr_lookback_values=[2, 3, 4, 5, 6],
        )
        assert result["volatility_regime"] == "normal"
        assert result["volatility_scalar"] == 1.0

    def test_high_regime_scales_down_risk(self):
        # atr sits above every value in the lookback window -> percentile 100 -> high/0.5x
        result = calculate_position_volatility(
            capital=100_000, risk_pct=1, entry=100, stop_loss=95, atr=100.0,
            atr_lookback_values=[2, 3, 4, 5, 6],
        )
        assert result["volatility_regime"] == "high"
        assert result["volatility_scalar"] == 0.5
        # risk_amount should be exactly half of the unscaled 1% risk
        assert result["risk_amount"] == 500.0

    def test_elevated_regime_between_60_and_80_percentile(self):
        # 10-value window; atr ranks at the 7th value -> 70th percentile -> elevated/0.75x
        lookback = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = calculate_position_volatility(
            capital=100_000, risk_pct=1, entry=100, stop_loss=95, atr=7,
            atr_lookback_values=lookback,
        )
        assert result["volatility_regime"] == "elevated"
        assert result["volatility_scalar"] == 0.75

    def test_missing_atr_falls_back_to_base_sizing(self):
        result = calculate_position_volatility(
            capital=100_000, risk_pct=1, entry=100, stop_loss=95, atr=0,
        )
        # falls back to calculate_position()'s plain output shape
        assert result["volatility_regime"] == "normal"
        assert result["risk_amount"] == 1000.0

    def test_no_lookback_values_assumes_normal_regime(self):
        result = calculate_position_volatility(
            capital=100_000, risk_pct=1, entry=100, stop_loss=95, atr=5.0,
            atr_lookback_values=None,
        )
        assert result["volatility_regime"] == "normal"
        assert result["atr_percentile"] == 50.0

    def test_zero_risk_distance_returns_error(self):
        result = calculate_position_volatility(
            capital=100_000, risk_pct=1, entry=100, stop_loss=100, atr=5.0,
        )
        assert "error" in result


class TestCalculateRiskReward:
    def test_good_ratio_at_or_above_2(self):
        result = calculate_risk_reward(entry=100, stop_loss=95, target=110)
        assert result["risk"] == 5.0
        assert result["reward"] == 10.0
        assert result["ratio"] == 2.0
        assert result["label"] == "Good"

    def test_average_ratio_between_1_and_2(self):
        result = calculate_risk_reward(entry=100, stop_loss=95, target=105)
        assert result["ratio"] == 1.0
        assert result["label"] == "Average"

    def test_poor_ratio_below_1(self):
        result = calculate_risk_reward(entry=100, stop_loss=95, target=102)
        assert result["ratio"] < 1.0
        assert result["label"] == "Poor"

    def test_zero_risk_returns_zero_ratio_not_a_crash(self):
        result = calculate_risk_reward(entry=100, stop_loss=100, target=110)
        assert result["ratio"] == 0

    def test_short_trade_uses_absolute_distances(self):
        # target below entry, stop above entry (short setup) — both risk
        # and reward must come out positive, not negative/inverted.
        result = calculate_risk_reward(entry=100, stop_loss=105, target=90)
        assert result["risk"] == 5.0
        assert result["reward"] == 10.0
        assert result["ratio"] == 2.0
