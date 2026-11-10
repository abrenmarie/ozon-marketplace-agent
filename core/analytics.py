"""Competitor price observations and SKU unit-economics calculations"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests
from cachetools import TTLCache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.pricing import (
    PricingValidationError,
    calculate_margin,
    calculate_break_even_price,
    calculate_minimum_price,
    calculate_net_profit,
    calculate_roi,
    round_money,
)
from domain.validation import default_portfolio, validate_portfolio

logger = logging.getLogger(__name__)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class PriceObservation:
    price: Decimal | None
    source: str  # real, simulated, unavailable
    status: str
    competitor_sku: str
    observed_at: str = field(default_factory=_timestamp)


class OzonSmartAgent:
    def __init__(self, config_path: str | None = None, *,
                 config: Mapping[str, Any] | None = None, data_mode: str | None = None):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.config_path = config_path or os.path.join(self.base_dir, "data", "portfolio_ozon.json")
        self.request_timeout = float(os.getenv("OZON_REQUEST_TIMEOUT", "4"))
        self.cache_ttl = max(0, int(os.getenv("PRICE_CACHE_TTL_SECONDS", "120")))
        legacy_demo = os.getenv("DEMO_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.data_mode = data_mode or ("demo" if legacy_demo else os.getenv("DATA_MODE", "production").lower())
        if self.data_mode not in {"demo", "production"}:
            raise ValueError("DATA_MODE must be 'demo' or 'production'.")
        self._price_cache: TTLCache = TTLCache(maxsize=512, ttl=max(1, self.cache_ttl))
        self._cache_lock = threading.RLock()
        self._session = self._build_session()
        self._external_config = config is not None
        self.config = validate_portfolio(config) if config is not None else default_portfolio()
        if config is None:
            self.load_config()

    @property
    def demo_mode(self) -> bool:
        return self.data_mode == "demo"

    def set_data_mode(self, mode: str) -> None:
        if mode not in {"demo", "production"}:
            raise ValueError("Режим данных должен быть demo или production.")
        self.data_mode = mode

    def set_portfolio(self, config: Mapping[str, Any]) -> None:
        self.config = validate_portfolio(config)
        self._external_config = True

    @staticmethod
    def _build_session() -> requests.Session:
        retry_total = max(0, int(os.getenv("OZON_RETRY_TOTAL", "2")))
        retry = Retry(
            total=retry_total,
            connect=retry_total,
            read=retry_total,
            status=retry_total,
            backoff_factor=0.35,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({
            "User-Agent": "OzonSmartAgent/0.3 (local seller operations toolkit)",
            "Accept-Language": "ru-RU,ru;q=0.9",
        })
        return session

    def load_config(self) -> None:
        if self._external_config:
            return
        if not os.path.exists(self.config_path):
            self.config = default_portfolio()
            return
        with open(self.config_path, "r", encoding="utf-8") as config_file:
            self.config = validate_portfolio(json.load(config_file))

    @staticmethod
    def _parse_price(raw_price: Any) -> Decimal | None:
        normalized = re.sub(r"[\s\u00a0\u200b₽]", "", str(raw_price)).replace(",", ".")
        normalized = re.sub(r"[^\d.]", "", normalized)
        if not normalized:
            return None
        try:
            value = Decimal(normalized)
        except InvalidOperation:
            return None
        return value if value.is_finite() and value > 0 else None

    def fetch_real_ozon_price(self, competitor_sku: str) -> PriceObservation:
        if not competitor_sku:
            return PriceObservation(None, "unavailable", "Не указан SKU конкурента", "")
        if competitor_sku.startswith("COMP-"):
            return PriceObservation(None, "unavailable", "Демо-SKU не запрашивается", competitor_sku)
        with self._cache_lock:
            cached = self._price_cache.get(competitor_sku)
        if cached is not None:
            return cached

        safe_competitor_sku = quote(competitor_sku, safe="")
        url = f"https://api.ozon.ru/composer-api.bx/page/json/v2?url=/product/{safe_competitor_sku}"
        try:
            response = self._session.get(url, timeout=(self.request_timeout, self.request_timeout))
            response.raise_for_status()
            payload = response.json()
            widgets = payload.get("widgetStates", {}) if isinstance(payload, dict) else {}
            if not isinstance(widgets, dict):
                widgets = {}
            for widget_key, widget_value in widgets.items():
                if "webPrice" not in widget_key:
                    continue
                price_data = json.loads(widget_value) if isinstance(widget_value, str) else widget_value
                if not isinstance(price_data, dict):
                    continue
                price = self._parse_price(price_data.get("price", ""))
                if price is not None:
                    observation = PriceObservation(
                        price, "real", "Цена разобрана из публичного ответа Ozon", competitor_sku
                    )
                    if self.cache_ttl:
                        with self._cache_lock:
                            self._price_cache[competitor_sku] = observation
                    return observation
            observation = PriceObservation(None, "unavailable", "Цена не найдена в ответе Ozon", competitor_sku)
        except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError) as error:
            logger.warning("Ozon price lookup failed for SKU %s: %s", competitor_sku, error)
            observation = PriceObservation(None, "unavailable", "Не удалось получить цену с Ozon", competitor_sku)
        if self.cache_ttl:
            with self._cache_lock:
                self._price_cache[competitor_sku] = observation
        return observation

    def collect_competitor_prices(self) -> dict[str, PriceObservation]:
        """Fetch public observations; synthetic values are opt-in and never drive recommendations."""
        self.load_config()
        observations: dict[str, PriceObservation] = {}
        for sku, info in self.config.get("products", {}).items():
            competitor_sku = info.get("target_competitor_sku", "")
            observation = self.fetch_real_ozon_price(competitor_sku)
            if (observation.price is None and competitor_sku.startswith("COMP-")
                    and self.data_mode == "demo"):
                current_price = Decimal(str(info["current_price"]))
                simulated = max(
                    Decimal("1"),
                    current_price * (Decimal("1") + Decimal(str(np.random.uniform(-0.07, 0.03)))),
                ).quantize(Decimal("0.01"))
                observation = PriceObservation(
                    simulated, "simulated",
                    "Демо-значение: не является наблюдением рынка и не используется для рекомендации",
                    competitor_sku,
                )
            observations[sku] = observation
        return observations

    # Backward-compatible method name retained for existing callers
    def simulate_osint_competitors(self) -> dict[str, PriceObservation]:
        return self.collect_competitor_prices()

    @staticmethod
    def _normalize_observation(value: Any, fallback_sku: str) -> PriceObservation:
        if isinstance(value, PriceObservation):
            return value
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            try:
                price = Decimal(str(value))
                if price.is_finite() and price > 0:
                    return PriceObservation(price, "real", "Передано вызывающим кодом", fallback_sku)
            except InvalidOperation:
                pass
        return PriceObservation(None, "unavailable", "Цена конкурента недоступна", fallback_sku)

    def calculate_unit_economics(self, competitor_prices: Mapping[str, Any]) -> pd.DataFrame:
        self.load_config()
        rows: list[dict[str, Any]] = []
        tax_rate = Decimal(str(self.config["tax_rate"]))
        for sku, info in self.config["products"].items():
            try:
                cost = Decimal(str(info["cost_price"]))
                current_price = Decimal(str(info["current_price"]))
                commission = Decimal(str(info["ozon_commission_pct"]))
                logistics = Decimal(str(info["logistics_fbo"]))
                minimum_margin = Decimal(str(info["min_margin_pct"]))
                acquiring = Decimal(str(info.get("acquiring_pct", 0)))
                storage = Decimal(str(info.get("storage_per_unit", 0)))
                advertising = Decimal(str(info.get("advertising_per_unit", 0)))
                return_cost = Decimal(str(info.get("return_cost_per_unit", 0)))
                other_costs = Decimal(str(info.get("other_costs_per_unit", 0)))
                stock = int(info["stock"])

                extra_costs = {
                    "acquiring_rate": acquiring,
                    "storage_per_unit": storage,
                    "advertising_per_unit": advertising,
                    "return_cost_per_unit": return_cost,
                    "other_costs_per_unit": other_costs,
                }
                profit = calculate_net_profit(
                    current_price, cost, commission, logistics, tax_rate, **extra_costs
                )
                margin = calculate_margin(profit, current_price)
                roi = calculate_roi(profit, cost)
                break_even_price = calculate_break_even_price(
                    cost, logistics, commission, tax_rate, **extra_costs
                )
                min_price = calculate_minimum_price(
                    cost, logistics, commission, tax_rate, minimum_margin, **extra_costs
                )
                competitor_sku = info.get("target_competitor_sku") or f"COMP-{sku}"
                observation = self._normalize_observation(competitor_prices.get(sku), competitor_sku)
                recommended_price: Decimal | None = None
                if observation.source == "real" and observation.price is not None:
                    target_price = observation.price - Decimal("10.00")
                    if target_price >= min_price:
                        recommended_price = target_price.quantize(Decimal("0.01"))
                        action = "MATCH_COMPETITOR_LOWER"
                    else:
                        recommended_price = round_money(min_price)
                        action = "HOLD_MIN_MARGIN_LIMIT"
                elif observation.source == "simulated":
                    action = "SIMULATION_ONLY"
                else:
                    action = "PRICE_DATA_UNAVAILABLE"
            except (PricingValidationError, InvalidOperation, ValueError, TypeError) as error:
                raise PricingValidationError(f"SKU {sku!r}: {error}") from error

            rows.append({
                "SKU": sku,
                "Название товара": info["name"],
                "Остаток (шт)": stock,
                "Себестоимость": float(round_money(cost)),
                "Текущая цена": float(round_money(current_price)),
                "SKU конкурента": competitor_sku,
                "Цена конкурента": float(round_money(observation.price)) if observation.price is not None else None,
                "Источник цены": observation.source,
                "Статус данных": observation.status,
                "Цена безубыточности": float(round_money(break_even_price)),
                "Мин. допустимая цена": float(round_money(min_price)),
                "Реком. цена": float(recommended_price) if recommended_price is not None else None,
                "Стратегия": action,
                "Net Profit": float(round_money(profit)),
                "Маржа, %": float((margin * 100).quantize(Decimal("0.01"))),
                "ROI, %": float((roi * 100).quantize(Decimal("0.01"))) if roi is not None else None,
                "Затраты на единицу": float(round_money(
                    cost + logistics + storage + advertising + return_cost + other_costs
                )),
                "Stock Left": stock,
            })
        return pd.DataFrame(rows)
