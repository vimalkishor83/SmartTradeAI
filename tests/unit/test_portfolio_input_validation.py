import pytest

from app.api.v1.portfolio import _optional_positive_float, _positive_float


def test_positive_float_rejects_non_finite_and_non_positive_values():
    with pytest.raises(ValueError):
        _positive_float(float("nan"), "quantity")
    with pytest.raises(ValueError):
        _positive_float(0, "quantity")
    with pytest.raises(ValueError):
        _positive_float(-1, "quantity")


def test_optional_positive_float_allows_clearing_a_level():
    assert _optional_positive_float(None, "stop_loss") is None
    assert _optional_positive_float("", "stop_loss") is None
    assert _optional_positive_float("95.5", "stop_loss") == 95.5
