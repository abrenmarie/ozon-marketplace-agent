from decimal import Decimal
import pytest

from core.pricing import (
    PricingValidationError, calculate_margin, calculate_minimum_price,
    calculate_net_profit, calculate_roi,
)


def test_net_profit_uses_decimal_arithmetic():
    result = calculate_net_profit("1500.00", "500.00", "0.15", "100.00", "0.06")
    assert result == Decimal("585.00")


def test_margin_is_fraction():
    assert calculate_margin("585", "1500") == Decimal("0.39")


def test_negative_margin_is_preserved():
    assert calculate_margin("-10", "100") == Decimal("-0.1")


def test_minimum_price():
    result = calculate_minimum_price("500", "100", ".15", ".06", ".20")
    assert result.quantize(Decimal("0.01")) == Decimal("1016.95")


def test_roi_is_none_for_zero_cost():
    assert calculate_roi("12.50", "0") is None


@pytest.mark.parametrize("value", [True, None, "abc", "NaN", "Infinity", "-Infinity"])
def test_invalid_numbers_are_rejected(value):
    with pytest.raises(PricingValidationError):
        calculate_net_profit(value, 10, .1, 2, .06)


@pytest.mark.parametrize("value", [-1, "NaN", "Infinity", True, "x"])
def test_invalid_cost_is_rejected(value):
    with pytest.raises(PricingValidationError):
        calculate_net_profit(100, value, .1, 2, .06)


def test_zero_price_is_rejected():
    with pytest.raises(PricingValidationError):
        calculate_net_profit(0, 10, .1, 2, .06)


def test_unachievable_margin_is_rejected():
    with pytest.raises(PricingValidationError, match="недостижима"):
        calculate_minimum_price(100, 10, .6, .2, .2)


def test_invalid_rate_is_rejected():
    with pytest.raises(PricingValidationError):
        calculate_net_profit(100, 10, 1.01, 2, .06)
