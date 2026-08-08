import json
import os
import datetime
import numpy as np
import pandas as pd
import streamlit as st
from core.analytics import OzonSmartAgent

st.set_page_config(
    page_title="Ozon Smart Agent — ИИ-Автопилот",
    page_icon="🤖",
    layout="wide"
)

CONFIG_PATH = os.path.join("data", "portfolio_ozon.json")

def load_config():
    if "config" not in st.session_state:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                st.session_state.config = json.load(f)
        else:
            st.session_state.config = {"currency": "RUB", "tax_rate": 0.06, "products": {}}

def save_config():
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(st.session_state.config, f, ensure_ascii=False, indent=2)
    st.session_state.agent = OzonSmartAgent()
    st.toast("Конфигурация успешно сохранена и агентом подхвачена!", icon="💾")

load_config()

if "agent" not in st.session_state:
    st.session_state.agent = OzonSmartAgent()

if "last_osint_time" not in st.session_state:
    st.session_state.last_osint_time = None

agent = st.session_state.agent

with st.sidebar:
    st.title("🤖 ИИ-Управление Ozon")
    st.markdown("---")
    
    if st.button("🚀 Запустить OSINT-сканирование", use_container_width=True, type="primary"):
        st.session_state.competitor_prices = agent.simulate_osint_competitors()
        st.session_state.last_osint_time = datetime.datetime.now().strftime("%H:%M:%S")
        st.toast("Парсинг цен конкурентов завершен!", icon="📡")
        st.rerun()

    if st.session_state.last_osint_time:
        st.caption(f"⏱️ Последнее сканирование: **{st.session_state.last_osint_time}**")
    else:
        st.caption("ℹ️ Нажмите кнопку выше для обновления цен конкурентов.")

    st.markdown("---")
    st.info("💡 Данные юнит-экономики рассчитываются в реальном времени с учетом комиссии Ozon, FBO и налогов.")

st.title("🛡️ Ozon Smart Agent — Панель управления и ИИ-Автопилот")
st.markdown("---")

tab_analytics, tab_osint, tab_manage = st.tabs([
    "📊 Аналитика и Автопилот", 
    "🕵️‍♂️ OSINT-Мониторинг", 
    "⚙️ Управление SKU (JSON)"
])

with tab_analytics:
    if "competitor_prices" not in st.session_state:
        st.session_state.competitor_prices = agent.simulate_osint_competitors()
    
    df_analytics = agent.calculate_unit_economics(st.session_state.competitor_prices)
    advice_list = agent.generate_executive_advice(df_analytics)

    st.subheader("📈 Ключевые показатели портфеля")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total_products = len(df_analytics)
        st.metric("Товаров в управлении (SKU)", total_products)
        
    with col2:
        total_profit = df_analytics["Net Profit"].sum() if not df_analytics.empty else 0.0
        st.metric("Прогнозируемая чистая прибыль", f"{total_profit:,.2f} ₽")
        
    with col3:
        critical_stocks = len(df_analytics[df_analytics["Stock Left"] <= 5]) if not df_analytics.empty else 0
        st.metric("Критический остаток (<= 5 шт)", critical_stocks, delta="-Требует поставки" if critical_stocks > 0 else "Запасы в норме", delta_color="inverse" if critical_stocks > 0 else "normal")

    st.markdown("---")

    st.subheader("🎯 ИИ-Директор: стратегические указания")
    if advice_list:
        for advice in advice_list:
            if "OVERSTOCK NOTICE" in advice:
                st.warning(f"⚠️ **Избыток запасов:** {advice.replace('OVERSTOCK NOTICE:', '')}")
            elif "HIGH PERFORMANCE" in advice:
                st.success(f"🔥 **Высокая маржинальность:** {advice.replace('HIGH PERFORMANCE:', '')}")
            elif "CRITICAL" in advice or "GUARD" in advice:
                st.error(f"🚨 **Критическая угроза:** {advice}")
            else:
                st.info(f"💡 **Рекомендация:** {advice}")
    else:
        st.info("Нет активных рекомендаций. Все показатели в норме.")

    st.markdown("---")

    st.subheader("🔍 Юнит-экономика и динамический репрайсинг")
    
    if not df_analytics.empty:
        df_display = df_analytics.copy()
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.warning("Каталог товаров пуст. Добавьте SKU во вкладке «Управление SKU».")

    st.markdown("---")

    st.subheader("✍️ ИИ-Фабрика контента и SEO-оптимизация")
    
    if not df_analytics.empty and "SKU" in df_analytics.columns:
        selected_sku = st.selectbox("Выберите SKU для моментальной генерации SEO-описания:", df_analytics["SKU"].tolist())

        if selected_sku:
            seo_data = agent.generate_ai_seo_content(selected_sku)
            st.markdown(f"**Сгенерированное описание для {selected_sku}:**")
            st.info(seo_data['description'])
            st.markdown("**Автоматические SEO-теги и ключевые слова:**")
            st.code(seo_data["keywords"], language="text")
    else:
        st.info("Добавьте товары во вкладке управления, чтобы генерировать SEO-контент.")

with tab_osint:
    st.subheader("🕵️‍♂️ Детальный мониторинг конкурентов Ozon")
    st.caption("Отслеживание цен, ссылок на карточки и автоматический анализ демпинга.")

    if "competitor_prices" not in st.session_state:
        st.session_state.competitor_prices = agent.simulate_osint_competitors()

    comp_prices = st.session_state.competitor_prices
    products = st.session_state.config.get("products", {})

    if products:
        osint_table = []
        for sku, info in products.items():
            my_price = float(info.get("current_price", 0.0))
            comp_sku = info.get("target_competitor_sku", "")
            comp_url = info.get("target_competitor_url", "")

            # если ссылки нет, но есть SKU - генерируем ссылку на Ozon
            if not comp_url and comp_sku and not comp_sku.startswith("COMP-"):
                comp_url = f"https://www.ozon.ru/product/{comp_sku}"

            fetched_price = comp_prices.get(comp_sku, comp_prices.get(f"COMP-{sku}", my_price))
            diff = fetched_price - my_price
            diff_pct = (diff / my_price) * 100 if my_price > 0 else 0

            if fetched_price < my_price:
                status = "🔴 Демпинг"
            elif abs(fetched_price - my_price) < 1.0:
                status = "🟡 Равна вашей"
            else:
                status = "🟢 Выше вашей"

            osint_table.append({
                "Ваш SKU": sku,
                "Товар": info.get("name", ""),
                "Ваша цена": my_price,
                "SKU Конкурента": comp_sku if comp_sku else "—",
                "Цена конкурента": fetched_price,
                "Разница, ₽": diff,
                "Отклонение %": round(diff_pct, 1),
                "Статус": status,
                "Ссылка на Ozon": comp_url if comp_url else None
            })

        df_osint = pd.DataFrame(osint_table)

        st.dataframe(
            df_osint,
            column_config={
                "Ваша цена": st.column_config.NumberColumn(format="%.2f ₽"),
                "Цена конкурента": st.column_config.NumberColumn(format="%.2f ₽"),
                "Разница, ₽": st.column_config.NumberColumn(format="%+.2f ₽"),
                "Отклонение %": st.column_config.NumberColumn(format="%+.1f %%"),
                "Ссылка на Ozon": st.column_config.LinkColumn(
                    "Карточка товара", 
                    display_text="Открыть на Ozon 🔗"
                )
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("Реестр товаров пуст. Добавьте товары во вкладке управления.")

with tab_manage:
    st.header("Редактирование реестра товаров и контроль лимитов")
    
    tax_rate = st.session_state.config.get("tax_rate", 0.06)
    products = st.session_state.config.get("products", {})

    st.subheader("Список текущих SKU в JSON")
    
    if products:
        for sku, details in list(products.items()):
            p_curr = float(details.get("current_price", 0.0))
            c_cost = float(details.get("cost_price", 0.0))
            mu_ozon = float(details.get("ozon_commission_pct", 0.0))
            l_fbo = float(details.get("logistics_fbo", 0.0))
            margin_min = float(details.get("min_margin_pct", 0.0))
            
            net_profit = p_curr * (1 - tax_rate) - c_cost - (p_curr * mu_ozon) - l_fbo
            
            denominator = 1.0 - mu_ozon - tax_rate - margin_min
            p_min = (c_cost + l_fbo) / denominator if denominator > 0 else float('nan')

            with st.expander(f"📦 {sku} — {details.get('name', 'Без названия')}"):
                
                m_col1, m_col2, m_col3 = st.columns(3)
                with m_col1:
                    st.metric("Текущая цена (P_current)", f"{p_curr:,.2f} ₽")
                with m_col2:
                    st.metric(
                        "Чистая прибыль (Net Profit)", 
                        f"{net_profit:,.2f} ₽", 
                        delta=f"{(net_profit/p_curr)*100:.1f}% маржа" if p_curr > 0 else "0%"
                    )
                with m_col3:
                    price_delta = p_curr - p_min if not pd.isna(p_min) else 0
                    st.metric(
                        "Мин. цена (P_min)", 
                        f"{p_min:,.2f} ₽" if not pd.isna(p_min) else "Ошибка", 
                        delta=f"{price_delta:,.2f} ₽ запас" if price_delta >= 0 else "НИЖЕ ЛИМИТА!", 
                        delta_color="normal" if price_delta >= 0 else "inverse"
                    )

                st.markdown("---")

                col1, col2, col3 = st.columns(3)
                with col1:
                    new_name = st.text_input("Название товара", value=details.get("name", ""), key=f"name_{sku}")
                    new_stock = st.number_input("Остаток (шт)", value=int(details.get("stock", 0)), key=f"stock_{sku}")
                    new_comp_sku = st.text_input("Артикул конкурента Ozon", value=details.get("target_competitor_sku", ""), key=f"comp_sku_{sku}")
                    new_comp_url = st.text_input("Ссылка на карточку конкурента Ozon", value=details.get("target_competitor_url", ""), key=f"comp_url_{sku}")

                with col2:
                    new_cost = st.number_input("Себестоимость, ₽", value=c_cost, step=10.0, key=f"cost_{sku}")
                    new_price = st.number_input("Текущая цена, ₽", value=p_curr, step=50.0, key=f"price_{sku}")
                    new_commission = st.number_input("Комиссия Ozon (0.15 = 15%)", value=mu_ozon, step=0.01, format="%.2f", key=f"comm_{sku}")

                with col3:
                    new_fbo = st.number_input("Логистика FBO, ₽", value=l_fbo, step=5.0, key=f"fbo_{sku}")
                    new_margin_limit = st.number_input("Мин. маржа (0.20 = 20%)", value=margin_min, step=0.01, format="%.2f", key=f"margin_{sku}")

                btn_col1, btn_col2 = st.columns([1, 5])
                with btn_col1:
                    if st.button("Сохранить", key=f"save_{sku}"):
                        st.session_state.config["products"][sku] = {
                            "name": new_name,
                            "stock": new_stock,
                            "cost_price": new_cost,
                            "current_price": new_price,
                            "ozon_commission_pct": new_commission,
                            "logistics_fbo": new_fbo,
                            "min_margin_pct": new_margin_limit,
                            "target_competitor_sku": new_comp_sku,
                            "target_competitor_url": new_comp_url
                        }
                        save_config()
                        st.rerun()
                        
                with btn_col2:
                    if st.button("Удалить SKU", key=f"del_{sku}", type="secondary"):
                        del st.session_state.config["products"][sku]
                        save_config()
                        st.rerun()
    else:
        st.info("Каталог товаров пуст. Добавьте первый SKU ниже.")

    st.divider()

    st.subheader("➕ Добавить новый SKU в систему")
    
    with st.form("add_sku_form", clear_on_submit=True):
        f_col1, f_col2, f_col3 = st.columns(3)
        
        with f_col1:
            add_sku = st.text_input("Артикул / SKU (уникальный ID)*", placeholder="SKU-NEW-001")
            add_name = st.text_input("Название товара*", placeholder="Беспроводные наушники")
            add_stock = st.number_input("Запас на складе", min_value=0, value=100)
            add_comp_sku = st.text_input("SKU конкурента Ozon", placeholder="123456789")
            add_comp_url = st.text_input("Ссылка на Ozon конкурента", placeholder="https://www.ozon.ru/product/123456789")

        with f_col2:
            add_cost = st.number_input("Себестоимость, ₽*", min_value=0.0, value=500.0, step=50.0)
            add_price = st.number_input("Продажная цена, ₽*", min_value=0.0, value=1500.0, step=100.0)
            add_comm = st.number_input("Комиссия Ozon (0.15 = 15%)*", min_value=0.0, max_value=1.0, value=0.15, step=0.01)

        with f_col3:
            add_fbo = st.number_input("Расходы FBO, ₽*", min_value=0.0, value=120.0, step=10.0)
            add_margin = st.number_input("Целевая мин. маржа (0.20 = 20%)*", min_value=0.0, max_value=1.0, value=0.20, step=0.01)

        submitted = st.form_submit_button("Добавить SKU в реестр", use_container_width=True)
        
        if submitted:
            if not add_sku or not add_name:
                st.error("Заполните обязательные поля: SKU и Название!")
            elif add_sku in st.session_state.config["products"]:
                st.error(f"SKU '{add_sku}' уже существует!")
            else:
                st.session_state.config["products"][add_sku] = {
                    "name": add_name,
                    "stock": add_stock,
                    "cost_price": add_cost,
                    "current_price": add_price,
                    "ozon_commission_pct": add_comm,
                    "logistics_fbo": add_fbo,
                    "min_margin_pct": add_margin,
                    "target_competitor_sku": add_comp_sku,
                    "target_competitor_url": add_comp_url
                }
                save_config()
                st.success(f"SKU {add_sku} успешно добавлен!")
                st.rerun()