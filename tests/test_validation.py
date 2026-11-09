import pytest

from domain.validation import ConfigurationValidationError, validate_portfolio, validate_product

VALID = {
    "name": "Тест", "stock": 2, "cost_price": 100, "current_price": 300,
    "ozon_commission_pct": .15, "logistics_fbo": 20, "min_margin_pct": .2,
    "target_competitor_sku": "", "target_competitor_url": "",
}


def test_valid_portfolio_normalizes_currency():
    result = validate_portfolio({"currency": "rub", "tax_rate": .06, "products": {"SKU": VALID}})
    assert result["currency"] == "RUB"


@pytest.mark.parametrize("changes", [
    {"current_price": 0}, {"cost_price": -1}, {"stock": -1},
    {"ozon_commission_pct": 1.1}, {"min_margin_pct": 1.0},
    {"target_competitor_url": "http://ozon.ru/item"},
    {"target_competitor_url": "https://example.com/item"},
])
def test_invalid_product_is_rejected(changes):
    with pytest.raises(ConfigurationValidationError):
        validate_product("SKU", VALID | changes, .06)


def test_impossible_margin_is_rejected():
    with pytest.raises(ConfigurationValidationError):
        validate_product("SKU", VALID | {"ozon_commission_pct": .8}, .06)
