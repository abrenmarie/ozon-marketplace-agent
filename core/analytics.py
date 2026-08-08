import pandas as pd
import numpy as np
import json
import os
import requests

class OzonSmartAgent:
    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(__file__))
        self.config_path = os.path.join(self.base_dir, "data", "portfolio_ozon.json")
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        else:
            self.config = {"currency": "RUB", "tax_rate": 0.06, "products": {}}

    def fetch_real_ozon_price(self, competitor_sku: str) -> float:
        # пытается спарсить реальную цену товара Ozon по его SKU/артикулу, если Ozon блокирует запрос или SKU некорректный, возвращает None
        if not competitor_sku or competitor_sku.startswith("COMP-"):
            return None

        # обращение к публичному веб-API Ozon
        url = f"https://api.ozon.ru/composer-api.bx/page/json/v2?url=/product/{competitor_sku}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=4)
            if response.status_code == 200:
                data = response.json()
                widgets = data.get("widgetStates", {})
                for widget_key, widget_val in widgets.items():
                    if "webPrice" in widget_key:
                        price_data = json.loads(widget_val)
                        price_str = price_data.get("price", "").replace(" ", "").replace("₽", "").replace("\u200b", "")
                        if price_str.isdigit():
                            return float(price_str)
        except Exception:
            pass  # при любой ошибке парсинга срабатывает фоллбек
            
        return None

    def simulate_osint_competitors(self) -> dict:
        # модуль OSINT-разведки сначала пытается получить реальные цены конкурентов по SKU через Ozon API, а если не получается, то переходит на симуляцию рыночных колебаний
        self.load_config()
        competitor_prices = {}

        for sku, info in self.config.get("products", {}).items():
            comp_sku = info.get("target_competitor_sku", "")
            curr_price = float(info.get("current_price", 1000.0))

            real_price = self.fetch_real_ozon_price(comp_sku) if comp_sku else None

            if real_price and real_price > 0:
                competitor_prices[comp_sku] = real_price
            else:
                random_shift = np.random.uniform(-0.07, 0.03) * curr_price
                simulated_price = max(100.0, curr_price + random_shift)
                
                key_name = comp_sku if comp_sku else f"COMP-{sku}"
                competitor_prices[key_name] = round(simulated_price, 2)

        return competitor_prices

    def calculate_unit_economics(self, competitor_prices: dict) -> pd.DataFrame:
        self.load_config()
        results = []
        tax_rate = float(self.config.get("tax_rate", 0.06))
        
        for sku, info in self.config.get("products", {}).items():
            cost = float(info.get("cost_price", 0.0))
            current_price = float(info.get("current_price", 0.0))
            commission_pct = float(info.get("ozon_commission_pct", 0.0))
            logistics = float(info.get("logistics_fbo", 0.0))
            min_margin_pct = float(info.get("min_margin_pct", 0.0))
            stock = int(info.get("stock", 0))

            commission = current_price * commission_pct
            tax = current_price * tax_rate
            
            revenue = current_price
            expenses = cost + commission + logistics + tax
            net_profit = revenue - expenses
            margin_pct = net_profit / current_price if current_price > 0 else 0.0
            roi = net_profit / cost if cost > 0 else 0.0
            
            comp_sku = info.get("target_competitor_sku", f"COMP-{sku}")
            comp_price = competitor_prices.get(comp_sku, current_price)
            
            # стратегия демпинга перебить цену конкурента на 10 рублей
            target_pricing = comp_price - 10.0
            
            # нижний порог цены P_min
            denominator = 1.0 - commission_pct - tax_rate - min_margin_pct
            min_allowed_price = (cost + logistics) / denominator if denominator > 0 else (cost + logistics)
            
            if target_pricing >= min_allowed_price:
                recommended_price = target_pricing
                repricing_action = "MATCH_COMPETITOR_LOWER"
            else:
                recommended_price = min_allowed_price
                repricing_action = "HOLD_MIN_MARGIN_LIMIT"
                
            results.append({
                "SKU": sku,
                "Название товара": info.get("name", "Без названия"),
                "Остаток (шт)": stock,
                "Себестоимость": round(cost, 2),
                "Текущая цена": round(current_price, 2),
                "Цена конкурента": round(comp_price, 2),
                "Реком. цена": round(recommended_price, 2),
                "Стратегия": repricing_action,
                "Net Profit": round(net_profit, 2),
                "Margin %": round(margin_pct, 4),
                "ROI %": round(roi, 4),
                "Stock Left": stock
            })
            
        return pd.DataFrame(results)

    def generate_ai_seo_content(self, sku: str) -> dict:
        self.load_config()
        product = self.config.get("products", {}).get(sku)
        if not product:
            return {"description": "Товар не найден в конфигурации.", "keywords": ""}
            
        name = product.get("name", "Товар")
        description = (
            f"Премиальный продукт '{name}' высочайшего качества. "
            f"Разработан с учетом современных стандартов эргономики и надежности. "
            f"Идеально подходит как для повседневного использования, так и в качестве подарка. "
            f"Гарантия долговечности и оригинального качества."
        )
        
        keywords_base = [w.strip().lower() for w in name.split() if len(w) > 2]
        keywords = ", ".join(keywords_base + ["подарок", "премиум качество", "быстрая доставка fbo", "оригинал"])
        
        return {
            "description": description,
            "keywords": keywords
        }

    def generate_executive_advice(self, df_analytics: pd.DataFrame) -> list:
        advice_list = []
        if df_analytics.empty:
            return ["Добавьте товары в реестр для получения рекомендаций."]

        for _, row in df_analytics.iterrows():
            sku = row["SKU"]
            stock = row["Stock Left"]
            strategy = row["Стратегия"]
            margin = row["Margin %"]
            
            if stock <= 5:
                advice_list.append(f"CRITICAL STOCK: У товара {sku} осталось всего {stock} шт. Срочно оформите заявку на поставку FBO, чтобы избежати падения в выдаче.")
            elif stock > 40:
                advice_list.append(f"OVERSTOCK NOTICE: Высокий остаток товара {sku} ({stock} шт.). Рекомендуется подключить участие в акциях Ozon или установить скидку.")
                
            if strategy == "HOLD_MIN_MARGIN_LIMIT":
                advice_list.append(f"MARGIN GUARD TRIGGERED: Конкурент по {sku} опустил цену ниже допустимого. Система заблокировала цену для защиты минимальной маржи.")
            elif margin > 0.30:
                advice_list.append(f"HIGH PERFORMANCE: Товар {sku} показывает отличную маржинальность ({int(margin*100)}%). Рекомендуется увеличить рекламный budget в Трафаретах Ozon.")
                
        if not advice_list:
            advice_list.append("Все финансовые показатели и запасы находятся в пределах нормы.")
            
        return advice_list