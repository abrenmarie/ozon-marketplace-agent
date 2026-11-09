import unittest

from core.analytics import OzonSmartAgent, PriceObservation
from domain.validation import ConfigurationValidationError, validate_portfolio, validate_product


VALID_PRODUCT = {
    "name": "Тестовый товар",
    "stock": 10,
    "cost_price": 500,
    "current_price": 1_500,
    "ozon_commission_pct": 0.15,
    "logistics_fbo": 100,
    "min_margin_pct": 0.20,
    "target_competitor_sku": "COMP-TEST-01",
    "target_competitor_url": "",
}


def portfolio(product=None):
    return {
        "currency": "rub",
        "tax_rate": 0.06,
        "products": {"SKU-TEST-01": product or VALID_PRODUCT},
    }


class ProductValidationTests(unittest.TestCase):
    def test_normalizes_valid_portfolio(self):
        result = validate_portfolio(portfolio())

        self.assertEqual(result["currency"], "RUB")
        self.assertEqual(result["products"]["SKU-TEST-01"]["stock"], 10)

    def test_rejects_non_positive_price(self):
        invalid_product = VALID_PRODUCT | {"current_price": 0}

        with self.assertRaises(ConfigurationValidationError):
            validate_product("SKU-TEST-01", invalid_product, 0.06)

    def test_rejects_impossible_margin_formula(self):
        invalid_product = VALID_PRODUCT | {
            "ozon_commission_pct": 0.75,
            "min_margin_pct": 0.20,
        }

        with self.assertRaises(ConfigurationValidationError):
            validate_product("SKU-TEST-01", invalid_product, 0.06)

    def test_rejects_non_ozon_competitor_url(self):
        invalid_product = VALID_PRODUCT | {"target_competitor_url": "https://example.com/product"}

        with self.assertRaises(ConfigurationValidationError):
            validate_product("SKU-TEST-01", invalid_product, 0.06)


class PricingRecommendationTests(unittest.TestCase):
    def setUp(self):
        self.agent = OzonSmartAgent()
        self.agent.config = validate_portfolio(portfolio())
        self.agent.load_config = lambda: None

    def test_simulated_price_never_generates_a_recommendation(self):
        observations = {
            "SKU-TEST-01": PriceObservation(
                price=1_300,
                source="simulated",
                status="demo",
                competitor_sku="COMP-TEST-01",
            )
        }

        row = self.agent.calculate_unit_economics(observations).iloc[0]

        self.assertEqual(row["Стратегия"], "SIMULATION_ONLY")
        self.assertIsNone(row["Реком. цена"])

    def test_real_price_respects_minimum_margin(self):
        observations = {
            "SKU-TEST-01": PriceObservation(
                price=700,
                source="real",
                status="test",
                competitor_sku="COMP-TEST-01",
            )
        }

        row = self.agent.calculate_unit_economics(observations).iloc[0]

        self.assertEqual(row["Стратегия"], "HOLD_MIN_MARGIN_LIMIT")
        self.assertGreaterEqual(row["Реком. цена"], row["Мин. допустимая цена"])

    def test_unavailable_price_never_generates_a_recommendation(self):
        row = self.agent.calculate_unit_economics({}).iloc[0]

        self.assertEqual(row["Стратегия"], "PRICE_DATA_UNAVAILABLE")
        self.assertIsNone(row["Реком. цена"])
