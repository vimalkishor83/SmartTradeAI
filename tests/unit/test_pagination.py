"""Regression coverage for API pagination safety limits."""

from app.services.pagination import bounded_float, bounded_int, bounded_page, bounded_per_page


def test_page_is_positive_and_invalid_values_use_default():
    assert bounded_page("3") == 3
    assert bounded_page("0") == 1
    assert bounded_page("not-a-number") == 1


def test_page_size_is_clamped_to_response_budget():
    assert bounded_per_page("25") == 25
    assert bounded_per_page("0") == 1
    assert bounded_per_page("100000", maximum=100) == 100
    assert bounded_per_page("bad", default=30, maximum=50) == 30


def test_market_data_limit_can_use_a_larger_explicit_budget():
    assert bounded_per_page("1000", default=200, maximum=1000) == 1000
    assert bounded_per_page("-10", default=200, maximum=1000) == 1
    assert bounded_per_page("bad", default=200, maximum=1000) == 200


def test_generic_query_bounds_handle_invalid_and_extreme_values():
    assert bounded_int("-5", default=90, minimum=1, maximum=3650) == 1
    assert bounded_int("99999", default=90, minimum=1, maximum=3650) == 3650
    assert bounded_int("bad", default=90, minimum=1, maximum=3650) == 90
    assert bounded_float("150", default=0, minimum=0, maximum=100) == 100
    assert bounded_float("nan", default=0, minimum=0, maximum=100) == 0
    assert bounded_float("bad", default=0, minimum=0, maximum=100) == 0
