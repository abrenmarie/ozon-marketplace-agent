"""Validation rules for product configuration and unit economics"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse


class ConfigurationValidationError(ValueError):
    """Raised when configuration would produce unsafe or invalid calculations"""


def default_portfolio() -> dict[str, Any]:
    return {"currency": "RUB", "tax_rate": 0.06, "products": {}}


def _required_text(value: Any, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ConfigurationValidationError(f"{field_name}: ожидается текстовое значение.")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length or any(ord(ch) < 32 for ch in normalized):
        raise ConfigurationValidationError(f"{field_name}: некорректное текстовое значение.")
    return normalized


def _optional_text(value: Any, field_name: str, max_length: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigurationValidationError(f"{field_name}: ожидается текстовое значение.")
    normalized = value.strip()
    if len(normalized) > max_length or any(ord(ch) < 32 for ch in normalized):
        raise ConfigurationValidationError(f"{field_name}: некорректное текстовое значение.")
    return normalized


def _number(value: Any, field_name: str, *, minimum: float, maximum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ConfigurationValidationError(f"{field_name}: ожидается число.")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ConfigurationValidationError(f"{field_name}: ожидается число.") from error
    if not math.isfinite(result):
        raise ConfigurationValidationError(f"{field_name}: число должно быть конечным.")
    if result < minimum or (maximum is not None and result > maximum):
        raise ConfigurationValidationError(f"{field_name}: значение вне допустимого диапазона.")
    return result


def _stock(value: Any) -> int:
    numeric_value = _number(value, "Остаток", minimum=0)
    if not numeric_value.is_integer():
        raise ConfigurationValidationError("Остаток: ожидается целое число.")
    return int(numeric_value)


def _competitor_url(value: Any) -> str:
    url = _optional_text(value, "Ссылка на конкурента", 2048)
    if not url:
        return ""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (hostname == "ozon.ru" or hostname.endswith(".ozon.ru")):
        raise ConfigurationValidationError("Ссылка на конкурента должна быть HTTPS-ссылкой на домен ozon.ru.")
    return url


def validate_product(sku: Any, product: Mapping[str, Any], tax_rate: Any) -> dict[str, Any]:
    if not isinstance(product, Mapping):
        raise ConfigurationValidationError("Данные SKU должны быть объектом.")
    normalized_sku = _required_text(sku, "SKU", 128)
    tax = _number(tax_rate, "Налоговая ставка", minimum=0, maximum=0.999999)
    commission = _number(product.get("ozon_commission_pct", 0), "Комиссия Ozon", minimum=0, maximum=0.999999)
    margin = _number(product.get("min_margin_pct", 0), "Минимальная маржа", minimum=0, maximum=0.999999)
    if commission + tax + margin >= 1:
        raise ConfigurationValidationError(
            f"SKU {normalized_sku}: комиссия, налог и минимальная маржа должны быть в сумме меньше 100%."
        )
    return {
        "name": _required_text(product.get("name", ""), "Название товара", 255),
        "stock": _stock(product.get("stock", 0)),
        "cost_price": _number(product.get("cost_price", 0), "Себестоимость", minimum=0),
        "current_price": _number(product.get("current_price", 0), "Текущая цена", minimum=0.01),
        "ozon_commission_pct": commission,
        "logistics_fbo": _number(product.get("logistics_fbo", 0), "Логистика FBO", minimum=0),
        "min_margin_pct": margin,
        "target_competitor_sku": _optional_text(product.get("target_competitor_sku", ""), "SKU конкурента", 128),
        "target_competitor_url": _competitor_url(product.get("target_competitor_url", "")),
    }


def validate_portfolio(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise ConfigurationValidationError("Конфигурация должна быть JSON-объектом.")
    products = config.get("products", {})
    if not isinstance(products, Mapping):
        raise ConfigurationValidationError("Поле products должно быть объектом.")
    currency = _required_text(config.get("currency", "RUB"), "Валюта", 8).upper()
    tax_rate = _number(config.get("tax_rate", 0.06), "Налоговая ставка", minimum=0, maximum=0.999999)
    normalized = {
        _required_text(sku, "SKU", 128): validate_product(sku, product, tax_rate)
        for sku, product in products.items()
    }
    return {"currency": currency, "tax_rate": tax_rate, "products": normalized}
