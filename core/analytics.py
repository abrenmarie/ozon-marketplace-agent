"""Application service for competitor observations and SKU unit economics"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

import numpy as np
import pandas as pd
import requests
from cachetools import TTLCache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.pricing import (
    PricingValidationError,
    calculate_margin,
    calculate_minimum_price,
    calculate_net_profit,
    calculate_roi,
    round_money,
)
from domain.validation import default_portfolio, validate_portfolio

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PriceObservation:
    """A competitor price with its source and human-readable collection status"""
    price: Decimal | None
    source: str  # real, simulated, unavailable
    status: str
    competitor_sku: str


class OzonSmartAgent:
    def __init__(self, config_path: str | None = None):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.config_path = config_path or os.path.join(self.base_dir, "data", "portfolio_ozon.json")
        self.request_timeout = float(os.getenv("OZON_REQUEST_TIMEOUT", "4"))
        self.cache_ttl = max(0, int(os.getenv("PRICE_CACHE_TTL_SECONDS", "120")))
        self.demo_mode = os.getenv("DEMO_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}
        self._price_cache: TTLCache = TTLCache(maxsize=512, ttl=max(1, self.cache_ttl))
        self._cache_lock = threading.RLock()
        self._session = self._build_session()
        self.load_config()

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
            "User-Agent": "OzonSmartAgent/0.2 (local decision-support prototype)",
            "Accept-Language": "ru-RU,ru;q=0.9",
        })
        return session

    def load_config(self) -> None:
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

        url = f"https://api.ozon.ru/composer-api.bx/page/json/v2?url=/product/{competitor_sku}"
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
                    observation = PriceObservation(price, "real", "Получена с публичной страницы Ozon", competitor_sku)
                    if self.cache_ttl:
                        with self._cache_lock:
                            self._price_cache[competitor_sku] = observation
                    return observation
            observation = PriceObservation(None, "unavailable", "Цена не найдена в ответе Ozon", competitor_sku)
        except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError) as error:
            logger.warning("Ozon price lookup failed for SKU %s: %s", competitor_sku, error)
            observation = PriceObservation(None, "unavailable", "Не удалось получить цену с Ozon", competitor_sku)

        # Cache negative results briefly to avoid hammering an unavailable endpoint.
        if self.cache_ttl:
            with self._cache_lock:
                self._price_cache[competitor_sku] = observation
        return observation

    def collect_competitor_prices(self) -> dict[str, PriceObservation]:
        """Fetch observations; demo prices are explicitly marked and never drive repricing."""
        self.load_config()
        observations: dict[str, PriceObservation] = {}
        for sku, info in self.config.get("products", {}).items():
            competitor_sku = info.get("target_competitor_sku", "")
            observation = self.fetch_real_ozon_price(competitor_sku)
            if observation.price is None and competitor_sku.startswith("COMP-") and self.demo_mode:
                current_price = Decimal(str(info["current_price"]))
                simulated = max(Decimal("100"), current_price * (
                    Decimal("1") + Decimal(str(np.random.uniform(-0.07, 0.03)))
                )).quantize(Decimal("0.01"))
                observation = PriceObservation(
                    simulated, "simulated", "Демо-симуляция: не использовать для решения о цене", competitor_sku
                )
            observations[sku] = observation
        return observations

    # Backward-compatible method name used by earlier app versions
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
                stock = int(info["stock"])

                profit = calculate_net_profit(current_price, cost, commission, logistics, tax_rate)
                margin = calculate_margin(profit, current_price)
                roi = calculate_roi(profit, cost)
                min_price = calculate_minimum_price(cost, logistics, commission, tax_rate, minimum_margin)

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
                "Мин. допустимая цена": float(round_money(min_price)),
                "Реком. цена": float(recommended_price) if recommended_price is not None else None,
                "Стратегия": action,
                "Net Profit": float(round_money(profit)),
                "Маржа, %": float((margin * 100).quantize(Decimal("0.01"))),
                "ROI, %": float((roi * 100).quantize(Decimal("0.01"))) if roi is not None else None,
                "Stock Left": stock,
            })
        return pd.DataFrame(rows)

    def generate_ai_seo_content(self, sku: str) -> dict[str, str]:
        self.load_config()
        product = self.config["products"].get(sku)
        if not product:
            return {"description": "Товар не найден в конфигурации.", "keywords": ""}
        name = product["name"]
        description = (
            f"Премиальный продукт '{name}' высочайшего качества."
            "Разработан с учетом современных стандартов эргономики и надежности."
            "Идеально подходит как для повседневного использования, так и в качестве подарка."
            "Гарантия долговечности и оригинального качества."
        )
        keywords_base = [word.strip().lower() for word in name.split() if len(word) > 2]
        keywords = ", ".join(keywords_base + ["подарок", "премиум качество", "быстрая доставка fbo", "оригинал"])
        return {"description": description, "keywords": keywords}

    def generate_executive_advice(self, analytics: pd.DataFrame) -> list[str]:
        if analytics.empty:
            return ["Каталог пока пуст."]
        advice: list[str] = []
        for _, row in analytics.iterrows():
            sku, stock, strategy = row["SKU"], int(row["Stock Left"]), row["Стратегия"]
            if float(row["Net Profit"]) < 0:
                advice.append(f"LOSS RISK: SKU {sku}: отрицательная прибыль с единицы.")
            if stock <= 5:
                advice.append(f"CRITICAL STOCK: SKU {sku}: осталось {stock} шт.")
            elif stock > 40:
                advice.append(f"OVERSTOCK NOTICE: SKU {sku}: остаток {stock} шт.; проверьте оборачиваемость.")
            if strategy == "HOLD_MIN_MARGIN_LIMIT":
                advice.append(f"MARGIN GUARD TRIGGERED: SKU {sku}: конкурентная цена ниже безопасного порога.")
            elif strategy == "SIMULATION_ONLY":
                advice.append(f"PRICE DATA SIMULATED: SKU {sku}: демо-цена не используется для рекомендации.")
            elif strategy == "PRICE_DATA_UNAVAILABLE":
                advice.append(f"PRICE DATA UNAVAILABLE: SKU {sku}: нет подтвержденной цены конкурента.")
        return advice or ["Критичных сигналов по текущим правилам не обнаружено."]
