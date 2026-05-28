import pandas as pd
import numpy as np
import json
import os

class OzonSmartAgent:
    def __init__(self):
        base_dir = os.path.dirname(os.path.dirname(__file__))
        config_path = os.path.join(base_dir, "data", "portfolio_ozon.json")
        with open(config_path, "r") as f:
            self.config = json.load(f)

    def simulate_osint_competitors(self) -> dict:
        competitor_prices = {
            "COMP-CAP-01": 1220.0 + np.random.uniform(-30, 30),
            "COMP-HOOD-05": 3450.0 + np.random.uniform(-100, 100),
            "COMP-CASE-11": 900.0 + np.random.uniform(-20, 20)
        }
        return competitor_prices

    def calculate_unit_economics(self, competitor_prices: dict) -> pd.DataFrame:
        results = []
        tax_rate = self.config["tax_rate"]
        
        for sku, info in self.config["products"].items():
            cost = info["cost_price"]
            current_price = info["current_price"]
            commission_usd = current_price * info["ozon_commission_pct"]
            logistics = info["logistics_fbo"]
            tax = current_price * tax_rate
            
            revenue = current_price
            expenses = cost + commission_usd + logistics + tax
            net_profit = revenue - expenses
            margin_pct = net_profit / current_price if current_price > 0 else 0.0
            roi = net_profit / cost if cost > 0 else 0.0
            
            comp_sku = info["target_competitor_sku"]
            comp_price = competitor_prices.get(comp_sku, current_price)
            
            target_pricing = comp_price - 10.0
            min_allowed_price = (cost + logistics) / (1 - info["ozon_commission_pct"] - tax_rate - info["min_margin_pct"])
            
            if target_pricing >= min_allowed_price:
                recommended_price = target_pricing
                repricing_action = "MATCH_COMPETITOR_LOWER"
            else:
                recommended_price = min_allowed_price
                repricing_action = "HOLD_MIN_MARGIN_LIMIT"
                
            results.append({
                "SKU": sku,
                "Product Name": info["name"],
                "Stock Left": info["stock"],
                "Cost Price": round(cost, 2),
                "Current Price": round(current_price, 2),
                "Competitor Price": round(comp_price, 2),
                "Recommended Price": round(recommended_price, 2),
                "Repricing Strategy": repricing_action,
                "Net Profit": round(net_profit, 2),
                "Margin %": round(margin_pct, 4),
                "ROI %": round(roi, 4)
            })
            
        return pd.DataFrame(results)

    def generate_ai_seo_content(self, sku: str) -> dict:
        product = self.config["products"].get(sku)
        if not product:
            return {"description": "Product not found.", "keywords": ""}
            
        name = product["name"]
        description = f"Premium commercial grade {name}. Engineered for maximum durability and modern aesthetic ergonomics. Ideal for industry experts and professional daily utilization."
        keywords = f"{name.lower().replace(' ', ', ')}, premium quality, e-commerce top choice, optimized tech wear"
        
        return {
            "description": description,
            "keywords": keywords
        }

    def generate_executive_advice(self, df_analytics: pd.DataFrame) -> list:
        advice_list = []
        for _, row in df_analytics.iterrows():
            sku = row["SKU"]
            stock = row["Stock Left"]
            strategy = row["Repricing Strategy"]
            margin = row["Margin %"]
            
            if stock <= 5:
                advice_list.append(f"CRITICAL STOCK: {sku} has only {stock} units remaining. Replenish FBO warehouse immediately to avoid search ranking degradation.")
            elif stock > 40:
                advice_list.append(f"OVERSTOCK NOTICE: {sku} inventory allocation is high ({stock} units). Consider enrolling in Ozon global sales or setting temporary dynamic discount promotions.")
                
            if strategy == "HOLD_MIN_MARGIN_LIMIT":
                advice_list.append(f"MARGIN GUARD TRIGGERED: Competitor price for {sku} is too low. System locked your price to protect your minimum allowed margin threshold.")
            elif margin > 0.30:
                advice_list.append(f"HIGH PERFORMANCE: {sku} is generating excellent return metrics (Margin: {int(margin*100)}%). Scaling marketing ad spend via Ozon.Promotions is highly recommended.")
                
        if not advice_list:
            advice_list.append("Operational baseline stable. All financial parameters, margin thresholds, and inventory tracking bounds operating within normal parameters.")
            
        return advice_list