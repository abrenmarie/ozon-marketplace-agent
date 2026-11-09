"""Decimal-based pricing rules shared by the UI and future service layers"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal("0")


class PricingValidationError(ValueError):
    """Raised when a pricing input is invalid or a target is mathematically impossible"""


def as_decimal(name: str, value: Any, *, minimum: Decimal | None = None,
               maximum: Decimal | None = None, minimum_exclusive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise PricingValidationError(f"{name}: ожидается числовое значение.")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError) as exc:
        raise PricingValidationError(f"{name}: ожидается числовое значение.") from exc
    if not number.is_finite():
        raise PricingValidationError(f"{name}: значение должно быть конечным.")
    if minimum is not None:
        invalid = number <= minimum if minimum_exclusive else number < minimum
        if invalid:
            condition = "больше" if minimum_exclusive else "не меньше"
            raise PricingValidationError(f"{name}: значение должно быть {condition} {minimum}.")
    if maximum is not None and number > maximum:
        raise PricingValidationError(f"{name}: значение должно быть не больше {maximum}.")
    return number


def money(value: Any, name: str = "Сумма", *, allow_zero: bool = True) -> Decimal:
    return as_decimal(name, value, minimum=ZERO, minimum_exclusive=not allow_zero)


def rate(value: Any, name: str) -> Decimal:
    return as_decimal(name, value, minimum=ZERO, maximum=Decimal("1"))


def round_money(value: Any) -> Decimal:
    number = as_decimal("Сумма", value)
    return number.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_net_profit(price: Any, cost: Any, commission_rate: Any,
                         logistics: Any, tax_rate: Any) -> Decimal:
    """Profit per unit; percentages apply to selling price, costs are fixed per unit"""
    sale_price = money(price, "Цена", allow_zero=False)
    unit_cost = money(cost, "Себестоимость")
    commission = rate(commission_rate, "Комиссия")
    delivery = money(logistics, "Логистика")
    tax = rate(tax_rate, "Налог")
    return sale_price - unit_cost - delivery - sale_price * commission - sale_price * tax


def calculate_margin(profit: Any, revenue: Any) -> Decimal:
    net_profit = as_decimal("Прибыль", profit)
    sales = money(revenue, "Выручка", allow_zero=False)
    return net_profit / sales


def calculate_roi(profit: Any, cost: Any) -> Decimal | None:
    net_profit = as_decimal("Прибыль", profit)
    unit_cost = money(cost, "Себестоимость")
    return net_profit / unit_cost if unit_cost > ZERO else None


def calculate_minimum_price(cost: Any, logistics: Any, commission_rate: Any,
                            tax_rate: Any, target_margin: Any) -> Decimal:
    unit_cost = money(cost, "Себестоимость")
    delivery = money(logistics, "Логистика")
    commission = rate(commission_rate, "Комиссия")
    tax = rate(tax_rate, "Налог")
    margin = rate(target_margin, "Минимальная маржа")
    denominator = Decimal("1") - commission - tax - margin
    if denominator <= ZERO:
        raise PricingValidationError(
            "Минимальная маржа недостижима: комиссия, налог и целевая маржа "
            "в сумме должны быть меньше 100%."
        )
    return (unit_cost + delivery) / denominator
