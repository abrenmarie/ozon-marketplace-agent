"""Decimal-based unit economics with explicit variable rates and per-unit costs"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")


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
    return as_decimal(name, value, minimum=ZERO, maximum=ONE)


def round_money(value: Any) -> Decimal:
    return as_decimal("Сумма", value).quantize(CENT, rounding=ROUND_HALF_UP)


def _fixed_unit_costs(*values: tuple[str, Any]) -> Decimal:
    return sum((money(value, name) for name, value in values), ZERO)


def calculate_net_profit(
    price: Any,
    cost: Any,
    commission_rate: Any,
    logistics: Any,
    tax_rate: Any,
    *,
    acquiring_rate: Any = ZERO,
    storage_per_unit: Any = ZERO,
    advertising_per_unit: Any = ZERO,
    return_cost_per_unit: Any = ZERO,
    other_costs_per_unit: Any = ZERO,
) -> Decimal:
    """Profit per sold unit. Percentage fees apply to selling price; other costs are per unit"""
    sale_price = money(price, "Цена", allow_zero=False)
    unit_cost = money(cost, "Себестоимость")
    commission = rate(commission_rate, "Комиссия")
    acquiring = rate(acquiring_rate, "Эквайринг")
    delivery = money(logistics, "Логистика")
    tax = rate(tax_rate, "Налог")
    fixed_costs = _fixed_unit_costs(
        ("Хранение", storage_per_unit),
        ("Реклама", advertising_per_unit),
        ("Расходы на возвраты", return_cost_per_unit),
        ("Прочие расходы", other_costs_per_unit),
    )
    if commission + acquiring + tax > ONE:
        raise PricingValidationError("Комиссия, эквайринг и налог не могут превышать 100% цены.")
    return (sale_price * (ONE - commission - acquiring - tax)
            - unit_cost - delivery - fixed_costs)


def calculate_margin(profit: Any, revenue: Any) -> Decimal:
    net_profit = as_decimal("Прибыль", profit)
    sales = money(revenue, "Выручка", allow_zero=False)
    return net_profit / sales


def calculate_roi(profit: Any, cost: Any) -> Decimal | None:
    net_profit = as_decimal("Прибыль", profit)
    unit_cost = money(cost, "Себестоимость")
    return net_profit / unit_cost if unit_cost > ZERO else None


def calculate_minimum_price(
    cost: Any,
    logistics: Any,
    commission_rate: Any,
    tax_rate: Any,
    target_margin: Any,
    *,
    acquiring_rate: Any = ZERO,
    storage_per_unit: Any = ZERO,
    advertising_per_unit: Any = ZERO,
    return_cost_per_unit: Any = ZERO,
    other_costs_per_unit: Any = ZERO,
    target_profit_per_unit: Any = ZERO,
) -> Decimal:
    """Price needed to reach target margin and optional target profit per unit"""
    unit_cost = money(cost, "Себестоимость")
    delivery = money(logistics, "Логистика")
    commission = rate(commission_rate, "Комиссия")
    acquiring = rate(acquiring_rate, "Эквайринг")
    tax = rate(tax_rate, "Налог")
    margin = rate(target_margin, "Минимальная маржа")
    target_profit = money(target_profit_per_unit, "Целевая прибыль")
    fixed_costs = _fixed_unit_costs(
        ("Хранение", storage_per_unit),
        ("Реклама", advertising_per_unit),
        ("Расходы на возвраты", return_cost_per_unit),
        ("Прочие расходы", other_costs_per_unit),
    )
    denominator = ONE - commission - acquiring - tax - margin
    if denominator <= ZERO:
        raise PricingValidationError(
            "Минимальная цена недостижима: комиссия, эквайринг, налог и целевая маржа "
            "в сумме должны быть меньше 100%."
        )
    return (unit_cost + delivery + fixed_costs + target_profit) / denominator


def calculate_break_even_price(
    cost: Any, logistics: Any, commission_rate: Any, tax_rate: Any, **kwargs: Any
) -> Decimal:
    """Return the price at which per-unit profit is zero"""
    return calculate_minimum_price(
        cost, logistics, commission_rate, tax_rate, ZERO, **kwargs
    )
