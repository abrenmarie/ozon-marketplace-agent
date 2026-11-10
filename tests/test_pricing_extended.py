from decimal import Decimal

import pytest

from core.pricing import (
    PricingValidationError,
    calculate_break_even_price,
    calculate_minimum_price,
    calculate_net_profit,
)


def test_existing_profit_signature_remains_backward_compatible():
    assert calculate_net_profit("1500", "500", ".15", "100", ".06") == Decimal("585.00")


def test_extended_cost_model_includes_acquiring_and_per_unit_costs():
    result = calculate_net_profit(
        "1500", "500", ".15", "100", ".06",
        acquiring_rate=".01", storage_per_unit="3", advertising_per_unit="7",
        return_cost_per_unit="2", other_costs_per_unit="4",
    )
    assert result == Decimal("554.00")


def test_minimum_price_includes_all_cost_components():
    result = calculate_minimum_price(
        "500", "100", ".15", ".06", ".20",
        acquiring_rate=".01", storage_per_unit="3", advertising_per_unit="7",
        return_cost_per_unit="2", other_costs_per_unit="4",
    )
    assert result.quantize(Decimal("0.01")) == Decimal("1062.07")


def test_break_even_price_targets_zero_profit():
    result = calculate_break_even_price("500", "100", ".15", ".06")
    assert calculate_net_profit(result, "500", ".15", "100", ".06").quantize(
        Decimal("0.01")
    ) == Decimal("0.00")


def test_unachievable_target_margin_including_acquiring_is_rejected():
    with pytest.raises(PricingValidationError, match="недостижима"):
        calculate_minimum_price("100", "0", ".45", ".2", ".2", acquiring_rate=".2")
