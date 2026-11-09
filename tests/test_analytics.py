import json
from decimal import Decimal

import pytest

from core.analytics import OzonSmartAgent, PriceObservation
from domain.validation import validate_portfolio


PRODUCT = {
    "name": "Тестовый товар",
    "stock": 10,
    "cost_price": 500,
    "current_price": 1500,
    "ozon_commission_pct": .15,
    "logistics_fbo": 100,
    "min_margin_pct": .20,
    "target_competitor_sku": "123456789",
    "target_competitor_url": "",
}


@pytest.fixture
def agent(tmp_path):
    config_path = tmp_path / "portfolio.json"
    config_path.write_text(json.dumps({
        "currency": "RUB", "tax_rate": .06, "products": {"SKU-01": PRODUCT}
    }), encoding="utf-8")
    instance = OzonSmartAgent(str(config_path))
    yield instance
    instance._session.close()


def test_analytics_uses_shared_decimal_pricing_core(agent):
    result = agent.calculate_unit_economics({
        "SKU-01": PriceObservation(Decimal("1200"), "real", "test", "123456789")
    })
    row = result.iloc[0]
    assert row["Net Profit"] == 585.0
    assert row["Маржа, %"] == 39.0
    assert row["Реком. цена"] == 1190.0


def test_simulated_observation_never_recommends_price(agent):
    result = agent.calculate_unit_economics({
        "SKU-01": PriceObservation(Decimal("1200"), "simulated", "demo", "COMP-01")
    })
    row = result.iloc[0]
    assert row["Стратегия"] == "SIMULATION_ONLY"
    assert row["Реком. цена"] is None


def test_unavailable_observation_never_recommends_price(agent):
    result = agent.calculate_unit_economics({})
    row = result.iloc[0]
    assert row["Стратегия"] == "PRICE_DATA_UNAVAILABLE"
    assert row["Реком. цена"] is None


def test_margin_guard_uses_minimum_price(agent):
    result = agent.calculate_unit_economics({
        "SKU-01": PriceObservation(Decimal("700"), "real", "test", "123456789")
    })
    row = result.iloc[0]
    assert row["Стратегия"] == "HOLD_MIN_MARGIN_LIMIT"
    assert row["Реком. цена"] >= row["Мин. допустимая цена"]


def test_price_parser_handles_russian_currency_format(agent):
    assert agent._parse_price("1 234,50 ₽") == Decimal("1234.50")
    assert agent._parse_price("—") is None


def test_competitor_fetch_is_cached(agent, monkeypatch):
    calls = []
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"widgetStates": {"webPrice": json.dumps({"price": "1 234 ₽"})}}
    def fake_get(*args, **kwargs):
        calls.append(1)
        return Response()
    monkeypatch.setattr(agent._session, "get", fake_get)
    first = agent.fetch_real_ozon_price("123456789")
    second = agent.fetch_real_ozon_price("123456789")
    assert first.price == Decimal("1234")
    assert second == first
    assert len(calls) == 1


def test_http_session_has_retry_policy(agent):
    adapter = agent._session.get_adapter("https://")
    retry = adapter.max_retries
    assert retry.total == 2
    assert 429 in retry.status_forcelist
    assert 503 in retry.status_forcelist
