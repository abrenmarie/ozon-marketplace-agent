from __future__ import annotations

import datetime as dt
import json
import logging
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from core.analytics import OzonSmartAgent, PriceObservation
from core.pricing import PricingValidationError, calculate_margin, calculate_minimum_price, calculate_net_profit
from domain.validation import ConfigurationValidationError, default_portfolio, validate_portfolio, validate_product

st.set_page_config(
    page_title="Ozon Smart Agent",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "data" / "portfolio_ozon.json"
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

st.markdown("""
<style>
/* Hide Streamlit top header */
[data-testid="stHeader"] {
    display: none;
}

/* Hide Streamlit top decoration */
[data-testid="stDecoration"] {
    display: none;
}

/* Adjust content spacing */
.block-container {
    padding-top: 1.5rem;
}
:root { --ink:#182230; --muted:#667085; --line:#e4e7ec; --surface:#ffffff; --canvas:#f5f7fa;
        --blue:#315b9a; --blue-soft:#edf3fb; --green:#18794e; --green-soft:#eaf6ef;
        --red:#b42318; --red-soft:#fef0ef; --amber:#9a6700; --amber-soft:#fff7e6; }
.stApp { background:var(--canvas); color:var(--ink); }
.block-container { max-width:1480px; padding-top:2rem; padding-bottom:3rem; }
h1,h2,h3 { color:var(--ink); letter-spacing:-.025em; }
h1 { font-weight:700; }
[data-testid="stMetric"] { background:var(--surface); border:1px solid var(--line); border-radius:12px;
  padding:16px 18px; box-shadow:0 1px 2px rgba(16,24,40,.03); }
[data-testid="stMetricLabel"] { color:var(--muted); font-size:.82rem; }
[data-testid="stMetricValue"] { color:var(--ink); font-weight:700; }
div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:10px; overflow:hidden; }
div[role="radiogroup"] { gap:8px; }
div[role="radiogroup"] label { background:#fff; border:1px solid var(--line); padding:8px 14px;
  border-radius:8px; }
div[role="radiogroup"] label:has(input:checked) { background:var(--blue-soft); border-color:#b7c9e4; }
.stButton>button, .stFormSubmitButton>button { border-radius:8px; font-weight:600; }
div[data-testid="stExpander"] { border:1px solid var(--line); border-radius:10px; background:#fff; }
.small-muted { color:var(--muted); font-size:.88rem; }
.section-kicker { color:var(--muted); text-transform:uppercase; letter-spacing:.08em; font-size:.72rem; font-weight:700; }
.status-pill { display:inline-block; border-radius:999px; padding:4px 9px; font-size:.78rem; font-weight:600; }
.status-red { color:var(--red); background:var(--red-soft); }
.status-amber { color:var(--amber); background:var(--amber-soft); }
.status-green { color:var(--green); background:var(--green-soft); }
.status-neutral { color:#475467; background:#eef1f4; }
hr { border-color:var(--line); }
</style>
""", unsafe_allow_html=True)


def load_config() -> bool:
    if "config" in st.session_state:
        return True
    if not CONFIG_PATH.exists():
        st.session_state.config = default_portfolio()
        return True
    try:
        st.session_state.config = validate_portfolio(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        return True
    except (OSError, json.JSONDecodeError, ConfigurationValidationError) as exc:
        st.error(f"Не удалось прочитать каталог: {exc}")
        st.stop()
        return False


def save_config() -> bool:
    temporary_path = None
    try:
        normalized = validate_portfolio(st.session_state.config)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(dir=CONFIG_PATH.parent, prefix=".portfolio_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_path, CONFIG_PATH)
        st.session_state.config = normalized
        st.session_state.agent = OzonSmartAgent(str(CONFIG_PATH))
        st.toast("Изменения сохранены")
        return True
    except (OSError, TypeError, ValueError, ConfigurationValidationError) as exc:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
        st.error(f"Не удалось сохранить изменения: {exc}")
        logger.exception("Portfolio save failed")
        return False


def ensure_agent() -> OzonSmartAgent:
    if "agent" not in st.session_state:
        st.session_state.agent = OzonSmartAgent(str(CONFIG_PATH))
    return st.session_state.agent


def get_observations() -> dict[str, PriceObservation]:
    observations = st.session_state.get("observations")
    if observations is None:
        return {
            sku: PriceObservation(None, "unavailable", "Обновление ещё не выполнялось",
                                  product.get("target_competitor_sku", ""))
            for sku, product in st.session_state.config["products"].items()
        }
    return observations



def build_action_queue(analytics: pd.DataFrame) -> pd.DataFrame:
    columns = ["Приоритет", "SKU", "Товар", "Причина", "Текущая цена", "Мин. цена", "Рекомендация", "Источник"]
    if analytics.empty:
        return pd.DataFrame(columns=columns)
    items = []
    for _, row in analytics.iterrows():
        reasons = []
        priority = 4
        if row["Net Profit"] < 0:
            reasons.append("Отрицательная прибыль с единицы")
            priority = 1
        if row["Текущая цена"] < row["Мин. допустимая цена"]:
            reasons.append("Текущая цена ниже минимально допустимой")
            priority = min(priority, 1)
        if row["Стратегия"] == "HOLD_MIN_MARGIN_LIMIT":
            reasons.append("Цена конкурента ниже порога маржи")
            priority = min(priority, 1)
        if row["Остаток (шт)"] <= 5:
            reasons.append("Критически низкий остаток")
            priority = min(priority, 2)
        if row["Стратегия"] == "PRICE_DATA_UNAVAILABLE":
            reasons.append("Нет подтвержденной цены конкурента")
            priority = min(priority, 3)
        if row["Стратегия"] == "SIMULATION_ONLY":
            reasons.append("Демо-цена не является рыночным наблюдением")
            priority = min(priority, 3)
        if row["Стратегия"] == "MATCH_COMPETITOR_LOWER":
            reasons.append("Можно рассмотреть снижение в пределах маржи")
            priority = 4
        if reasons:
            recommendation = row["Реком. цена"]
            if row["Стратегия"] == "HOLD_MIN_MARGIN_LIMIT":
                recommendation = f"Не ниже {row['Мин. допустимая цена']:,.2f} ₽"
            elif row["Стратегия"] == "SIMULATION_ONLY":
                recommendation = "Нет – дождаться реальной цены"
            elif row["Стратегия"] == "PRICE_DATA_UNAVAILABLE":
                recommendation = "Нет – обновить источник"
            elif pd.notna(row["Реком. цена"]):
                recommendation = f"Проверить {row['Реком. цена']:,.2f} ₽"
            items.append({
                "Приоритет": priority, "SKU": row["SKU"], "Товар": row["Название товара"],
                "Причина": "; ".join(reasons), "Текущая цена": row["Текущая цена"],
                "Мин. цена": row["Мин. допустимая цена"], "Рекомендация": recommendation,
                "Источник": row["Источник цены"],
            })
    queue = pd.DataFrame(items, columns=columns)
    return queue.sort_values(["Приоритет", "SKU"]) if not queue.empty else queue


def money_columns(frame: pd.DataFrame, columns: list[str]) -> dict:
    return {name: st.column_config.NumberColumn(format="%.2f ₽") for name in columns}


load_config()
agent = ensure_agent()
config = st.session_state.config
products = config["products"]
observations = get_observations()

header_left, header_right = st.columns([4, 1])
with header_left:
    st.markdown('<div class="section-kicker">OZON SELLER DECISION SUPPORT</div>', unsafe_allow_html=True)
    st.title("Ozon Smart Agent")
    st.caption("Локальная панель контроля юнит-экономики и решений по ассортименту.")
with header_right:
    if st.button("Обновить цены", type="primary", use_container_width=True):
        with st.spinner("Получаем доступные наблюдения..."):
            st.session_state.observations = agent.collect_competitor_prices()
            st.session_state.observations_updated_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        st.rerun()

sections = ["Портфель", "Цены конкурентов", "Каталог", "Настройки"]
if "main_navigation" not in st.session_state:
    st.session_state.main_navigation = "Портфель"

nav_columns = st.columns(4)
for column, section_name in zip(nav_columns, sections):
    if column.button(
        section_name,
        use_container_width=True,
        type="primary" if st.session_state.main_navigation == section_name else "secondary",
        key=f"nav_{section_name}",
    ):
        st.session_state.main_navigation = section_name
        st.rerun()
nav = st.session_state.main_navigation
st.divider()

analytics = agent.calculate_unit_economics(observations)
queue = build_action_queue(analytics)
updated_at = st.session_state.get("observations_updated_at")
if updated_at:
    try:
        updated_label = dt.datetime.fromisoformat(updated_at).strftime("%d.%m.%Y %H:%M:%S %z")
    except ValueError:
        updated_label = updated_at
else:
    updated_label = "еще не обновлялись"

st.caption(f"Источник наблюдений: публичная страница Ozon; демо-данные явно помечаются. Последнее обновление: {updated_label}.")

if nav == "Портфель":
    st.markdown('<div class="section-kicker">PORTFOLIO OVERVIEW</div>', unsafe_allow_html=True)
    st.header("Состояние портфеля")
    loss_count = int((analytics["Net Profit"] < 0).sum()) if not analytics.empty else 0
    action_count = len(queue)
    real_count = int((analytics["Источник цены"] == "real").sum()) if not analytics.empty else 0
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("SKU в каталоге", len(analytics))
    k2.metric("Риск убытка", loss_count, delta="Требует внимания" if loss_count else "Не выявлен",
              delta_color="inverse" if loss_count else "normal")
    k3.metric("SKU в очереди действий", action_count)
    k4.metric("Подтвержденные цены", real_count)
    st.caption("Прибыль – расчет на одну единицу товара. Это не прогноз продаж и не прибыль по складскому остатку.")
    st.divider()

    st.subheader("Очередь действий")
    st.caption("Приоритеты строятся по правилам маржинальности, остаткам и достоверности конкурентных данных.")
    if queue.empty:
        st.success("По текущим правилам нет SKU, требующих немедленного действия.")
    else:
        st.dataframe(
            queue,
            column_config={
                "Приоритет": st.column_config.NumberColumn(format="%d"),
                **money_columns(queue, ["Текущая цена", "Мин. цена"]),
            },
            use_container_width=True, hide_index=True,
        )
    st.subheader("Показатели по SKU")
    if analytics.empty:
        st.info("Каталог пуст. Добавьте первый товар в разделе «Каталог».")
    else:
        portfolio_view = analytics[[
            "SKU", "Название товара", "Остаток (шт)", "Текущая цена", "Net Profit",
            "Маржа, %", "Мин. допустимая цена", "Реком. цена", "Источник цены", "Стратегия"
        ]].copy()
        st.dataframe(
            portfolio_view,
            column_config={
                **money_columns(portfolio_view, ["Текущая цена", "Net Profit", "Мин. допустимая цена", "Реком. цена"]),
                "Маржа, %": st.column_config.NumberColumn(format="%.2f %%"),
            },
            use_container_width=True, hide_index=True,
        )
elif nav == "Цены конкурентов":
    st.markdown('<div class="section-kicker">COMPETITOR INTELLIGENCE</div>', unsafe_allow_html=True)
    st.header("Цены конкурентов")
    st.caption("Наблюдение не равно подтвержденному рыночному факту. Только источник real участвует в расчете рекомендации.")
    if analytics.empty:
        st.info("Добавьте SKU в каталоге.")
    else:
        competitor_view = analytics[[
            "SKU", "Название товара", "SKU конкурента", "Текущая цена", "Цена конкурента",
            "Источник цены", "Статус данных", "Мин. допустимая цена", "Реком. цена", "Стратегия"
        ]]
        st.dataframe(
            competitor_view,
            column_config={
                **money_columns(competitor_view, ["Текущая цена", "Цена конкурента", "Мин. допустимая цена", "Реком. цена"]),
            },
            use_container_width=True, hide_index=True,
        )
    st.caption(f"TTL кэша наблюдений: {agent.cache_ttl} сек.")

elif nav == "Каталог":
    st.markdown('<div class="section-kicker">PRODUCT MASTER DATA</div>', unsafe_allow_html=True)
    st.header("Каталог SKU")
    st.caption("Изменения проходят доменную валидацию до записи в JSON.")
    if products:
        for sku, details in list(products.items()):
            with st.expander(f"{sku} · {details['name']}"):
                with st.form(f"edit_{sku}"):
                    c1, c2, c3 = st.columns(3)
                    name = c1.text_input("Название", details["name"])
                    stock = c1.number_input("Остаток, шт.", min_value=0, value=int(details["stock"]), step=1)
                    competitor_sku = c1.text_input("SKU конкурента", details["target_competitor_sku"])
                    competitor_url = c1.text_input("Ссылка на Ozon", details["target_competitor_url"])
                    cost = c2.number_input("Себестоимость, ₽", min_value=0.0, value=float(details["cost_price"]), step=10.0)
                    price = c2.number_input("Текущая цена, ₽", min_value=0.01, value=float(details["current_price"]), step=10.0)
                    commission = c2.number_input("Комиссия (доля)", min_value=0.0, max_value=0.999999, value=float(details["ozon_commission_pct"]), step=0.01, format="%.4f")
                    logistics = c3.number_input("Логистика FBO, ₽", min_value=0.0, value=float(details["logistics_fbo"]), step=5.0)
                    margin = c3.number_input("Минимальная маржа (доля)", min_value=0.0, max_value=0.999999, value=float(details["min_margin_pct"]), step=0.01, format="%.4f")
                    submitted = st.form_submit_button("Сохранить изменения", type="primary")
                if submitted:
                    try:
                        st.session_state.config["products"][sku] = validate_product(sku, {
                            "name": name, "stock": stock, "target_competitor_sku": competitor_sku,
                            "target_competitor_url": competitor_url, "cost_price": cost, "current_price": price,
                            "ozon_commission_pct": commission, "logistics_fbo": logistics, "min_margin_pct": margin,
                        }, config["tax_rate"])
                        if save_config():
                            st.rerun()
                    except ConfigurationValidationError as exc:
                        st.error(str(exc))
                if st.button("Удалить SKU", key=f"delete_{sku}"):
                    del st.session_state.config["products"][sku]
                    if save_config():
                        st.rerun()
    else:
        st.info("Каталог пока пуст.")

    st.divider()
    st.subheader("Добавить товар")
    with st.form("add_product", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        new_sku = c1.text_input("SKU *")
        new_name = c1.text_input("Название *")
        new_stock = c1.number_input("Остаток, шт.", min_value=0, value=0, step=1)
        new_comp_sku = c1.text_input("SKU конкурента")
        new_cost = c2.number_input("Себестоимость, ₽", min_value=0.0, value=0.0, step=10.0)
        new_price = c2.number_input("Текущая цена, ₽", min_value=0.01, value=100.0, step=10.0)
        new_commission = c2.number_input("Комиссия (доля)", min_value=0.0, max_value=0.999999, value=0.15, step=0.01)
        new_logistics = c3.number_input("Логистика FBO, ₽", min_value=0.0, value=0.0, step=5.0)
        new_margin = c3.number_input("Минимальная маржа (доля)", min_value=0.0, max_value=0.999999, value=0.20, step=0.01)
        new_url = c3.text_input("Ссылка на Ozon")
        add = st.form_submit_button("Добавить SKU", type="primary")
    if add:
        normalized_sku = new_sku.strip()
        if not normalized_sku or normalized_sku in products:
            st.error("Укажите уникальный SKU.")
        else:
            try:
                st.session_state.config["products"][normalized_sku] = validate_product(normalized_sku, {
                    "name": new_name, "stock": new_stock, "target_competitor_sku": new_comp_sku,
                    "target_competitor_url": new_url, "cost_price": new_cost, "current_price": new_price,
                    "ozon_commission_pct": new_commission, "logistics_fbo": new_logistics, "min_margin_pct": new_margin,
                }, config["tax_rate"])
                if save_config():
                    st.rerun()
            except ConfigurationValidationError as exc:
                st.error(str(exc))

elif nav == "Настройки":
    st.markdown('<div class="section-kicker">WORKSPACE SETTINGS</div>', unsafe_allow_html=True)
    st.header("Настройки")
    st.subheader("Финансовые параметры")
    with st.form("settings_form"):
        tax_rate = st.number_input("Налоговая ставка (доля)", min_value=0.0, max_value=0.999999,
                                   value=float(config["tax_rate"]), step=0.01, format="%.4f")
        save_settings = st.form_submit_button("Сохранить настройки", type="primary")
    if save_settings:
        try:
            updated = dict(config)
            updated["tax_rate"] = tax_rate
            st.session_state.config = validate_portfolio(updated)
            if save_config():
                st.rerun()
        except ConfigurationValidationError as exc:
            st.error(str(exc))
    st.divider()
    st.subheader("Интеграция и надежность")
    st.write(f"**Среда:** `{os.getenv('APP_ENV', 'local')}`")
    st.write(f"**Демо-режим:** `{'включен' if agent.demo_mode else 'выключен'}`")
    st.write(f"**Таймаут HTTP:** `{agent.request_timeout:g} сек.`")
    st.write(f"**Повторные попытки:** `{os.getenv('OZON_RETRY_TOTAL', '2')}`")
    st.write(f"**TTL кэша цен:** `{agent.cache_ttl} сек.`")
    st.write("**Источник цен:** публичная страница Ozon; это не официальный Seller API.")
    st.info("Панель работает локально. Не публикуйте ее в сеть без аутентификации, TLS и разграничения доступа.")
