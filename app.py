from __future__ import annotations

import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

from core.analytics import OzonSmartAgent, PriceObservation
from core.import_export import (
    CatalogImportError,
    export_catalog_csv,
    export_catalog_xlsx,
    parse_catalog_upload,
)
from core.pricing import PricingValidationError
from core.storage import SQLiteRepository, StorageError
from domain.validation import ConfigurationValidationError, validate_product

st.set_page_config(
    page_title="Ozon Smart Agent",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed",
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "ozon_smart_agent.sqlite3"))).resolve()
LEGACY_JSON_PATH = DATA_DIR / "portfolio_ozon.json"
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

st.markdown(
    """
<style>
[data-testid="stHeader"], [data-testid="stDecoration"] { display: none; }
:root { --ink:#182230; --muted:#667085; --line:#e4e7ec; --surface:#ffffff; --canvas:#f5f7fa;
        --blue:#315b9a; --blue-soft:#edf3fb; --green:#18794e; --green-soft:#eaf6ef;
        --red:#b42318; --red-soft:#fef0ef; --amber:#9a6700; --amber-soft:#fff7e6; }
.stApp { background:var(--canvas); color:var(--ink); }
.block-container { max-width:1480px; padding-top:1.35rem; padding-bottom:3rem; }
h1,h2,h3 { color:var(--ink); letter-spacing:-.025em; }
h1 { font-weight:700; }
[data-testid="stMetric"] { background:var(--surface); border:1px solid var(--line); border-radius:12px;
  padding:16px 18px; box-shadow:0 1px 2px rgba(16,24,40,.03); }
[data-testid="stMetricLabel"] { color:var(--muted); font-size:.82rem; }
[data-testid="stMetricValue"] { color:var(--ink); font-weight:700; }
div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:10px; overflow:hidden; }
.stButton>button, .stFormSubmitButton>button, .stDownloadButton>button { border-radius:8px; font-weight:600; }
div[data-testid="stExpander"] { border:1px solid var(--line); border-radius:10px; background:#fff; }
.section-kicker { color:var(--muted); text-transform:uppercase; letter-spacing:.08em; font-size:.72rem; font-weight:700; }
.small-muted { color:var(--muted); font-size:.88rem; }
hr { border-color:var(--line); }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource
def get_repository(database_path: str, legacy_json_path: str) -> SQLiteRepository:
    return SQLiteRepository(database_path, legacy_json_path)


try:
    repository = get_repository(str(DATABASE_PATH), str(LEGACY_JSON_PATH))
    settings = repository.get_settings()
    portfolio = repository.load_portfolio()
except (StorageError, OSError) as exc:
    st.error(f"Не удалось открыть локальное хранилище: {exc}")
    st.stop()


def money_columns(frame: pd.DataFrame, columns: list[str]) -> dict:
    return {name: st.column_config.NumberColumn(format="%.2f ₽") for name in columns if name in frame.columns}


def build_action_queue(analytics: pd.DataFrame) -> pd.DataFrame:
    columns = ["Приоритет", "SKU", "Товар", "Причина", "Текущая цена", "Мин. цена", "Рекомендация", "Источник"]
    if analytics.empty:
        return pd.DataFrame(columns=columns)
    items: list[dict] = []
    for _, row in analytics.iterrows():
        reasons: list[str] = []
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
            reasons.append("Нет пригодной цены конкурента")
            priority = min(priority, 3)
        if row["Стратегия"] == "SIMULATION_ONLY":
            reasons.append("Демо-цена не является рыночным наблюдением")
            priority = min(priority, 3)
        if row["Стратегия"] == "MATCH_COMPETITOR_LOWER":
            reasons.append("Можно рассмотреть снижение в пределах маржи")
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
                "Приоритет": priority,
                "SKU": row["SKU"],
                "Товар": row["Название товара"],
                "Причина": "; ".join(reasons),
                "Текущая цена": row["Текущая цена"],
                "Мин. цена": row["Мин. допустимая цена"],
                "Рекомендация": recommendation,
                "Источник": row["Источник цены"],
            })
    result = pd.DataFrame(items, columns=columns)
    return result.sort_values(["Приоритет", "SKU"]) if not result.empty else result


def make_agent(current_portfolio: dict, current_settings: dict) -> OzonSmartAgent:
    return OzonSmartAgent(config=current_portfolio, data_mode=current_settings["data_mode"])


def observations_for_agent() -> dict[str, PriceObservation]:
    latest = repository.latest_price_observations()
    observations: dict[str, PriceObservation] = {}
    for sku, product in portfolio["products"].items():
        record = latest.get(sku)
        if record:
            price = Decimal(record["price"]) if record["price"] is not None else None
            observations[sku] = PriceObservation(
                price, record["source"], record["status"], record["competitor_sku"], record["observed_at"]
            )
        else:
            observations[sku] = PriceObservation(
                None, "unavailable", "Наблюдений пока нет", product.get("target_competitor_sku", "")
            )
    return observations


def save_recommendation_snapshot(frame: pd.DataFrame) -> None:
    for _, row in frame.iterrows():
        recommendation = row["Реком. цена"]
        rationale_by_strategy = {
            "MATCH_COMPETITOR_LOWER": "Цена конкурента позволяет рассмотреть снижение без нарушения минимальной маржи.",
            "HOLD_MIN_MARGIN_LIMIT": "Цена конкурента ниже порога; рекомендация ограничена минимально допустимой ценой.",
            "SIMULATION_ONLY": "Источник симулирован; ценовая рекомендация не формируется.",
            "PRICE_DATA_UNAVAILABLE": "Нет пригодного наблюдения; ценовая рекомендация не формируется.",
        }
        sku = str(row["SKU"])
        product = portfolio["products"].get(sku, {})
        repository.save_recommendation(
            sku=sku,
            competitor_price=row["Цена конкурента"],
            minimum_price=row["Мин. допустимая цена"],
            recommended_price=recommendation,
            strategy=str(row["Стратегия"]),
            rationale=rationale_by_strategy.get(str(row["Стратегия"]), "Расчет выполнен по текущим параметрам SKU."),
            data_source=str(row["Источник цены"]),
            context={
                "product_name": row["Название товара"],
                "current_price": row["Текущая цена"],
                "cost_price": row["Себестоимость"],
                "stock": row["Остаток (шт)"],
                "profit_per_unit": row["Net Profit"],
                "margin_pct": row["Маржа, %"],
                "roi_pct": row["ROI, %"],
                "break_even_price": row["Цена безубыточности"],
                "minimum_price": row["Мин. допустимая цена"],
                "tax_rate": portfolio["tax_rate"],
                "cost_parameters": {
                    key: product.get(key, 0) for key in (
                        "ozon_commission_pct", "acquiring_pct", "logistics_fbo",
                        "storage_per_unit", "advertising_per_unit",
                        "return_cost_per_unit", "other_costs_per_unit", "min_margin_pct",
                    )
                },
            },
        )


def product_editor(sku: str, details: dict, tax_rate: float, key_prefix: str) -> dict | None:
    with st.form(f"{key_prefix}_{sku}"):
        st.markdown(f"**{sku} · {details['name']}**")
        c1, c2, c3 = st.columns(3)
        with c1:
            name = st.text_input("Название", details["name"], key=f"{key_prefix}_{sku}_name")
            stock = st.number_input("Остаток, шт.", min_value=0, value=int(details["stock"]), step=1,
                                    key=f"{key_prefix}_{sku}_stock")
            competitor_sku = st.text_input("SKU конкурента", details["target_competitor_sku"],
                                           key=f"{key_prefix}_{sku}_competitor")
            competitor_url = st.text_input("Ссылка на Ozon", details["target_competitor_url"],
                                           key=f"{key_prefix}_{sku}_url")
        with c2:
            cost = st.number_input("Себестоимость, ₽", min_value=0.0, value=float(details["cost_price"]),
                                   step=10.0, key=f"{key_prefix}_{sku}_cost")
            price = st.number_input("Текущая цена, ₽", min_value=0.01, value=float(details["current_price"]),
                                    step=10.0, key=f"{key_prefix}_{sku}_price")
            commission = st.number_input("Комиссия Ozon (доля)", min_value=0.0, max_value=0.999999,
                                         value=float(details["ozon_commission_pct"]), step=0.01,
                                         format="%.4f", key=f"{key_prefix}_{sku}_commission")
            acquiring = st.number_input("Эквайринг (доля)", min_value=0.0, max_value=0.999999,
                                        value=float(details.get("acquiring_pct", 0)), step=0.005,
                                        format="%.4f", key=f"{key_prefix}_{sku}_acquiring")
            margin = st.number_input("Целевая маржа (доля)", min_value=0.0, max_value=0.999999,
                                     value=float(details["min_margin_pct"]), step=0.01,
                                     format="%.4f", key=f"{key_prefix}_{sku}_margin")
        with c3:
            logistics = st.number_input("Логистика FBO, ₽", min_value=0.0,
                                        value=float(details["logistics_fbo"]), step=5.0,
                                        key=f"{key_prefix}_{sku}_logistics")
            storage = st.number_input("Хранение на единицу, ₽", min_value=0.0,
                                      value=float(details.get("storage_per_unit", 0)), step=1.0,
                                      key=f"{key_prefix}_{sku}_storage")
            advertising = st.number_input("Реклама на единицу, ₽", min_value=0.0,
                                          value=float(details.get("advertising_per_unit", 0)), step=1.0,
                                          key=f"{key_prefix}_{sku}_advertising")
            returns = st.number_input("Возвраты на единицу, ₽", min_value=0.0,
                                      value=float(details.get("return_cost_per_unit", 0)), step=1.0,
                                      key=f"{key_prefix}_{sku}_returns")
            other = st.number_input("Прочие расходы на единицу, ₽", min_value=0.0,
                                    value=float(details.get("other_costs_per_unit", 0)), step=1.0,
                                    key=f"{key_prefix}_{sku}_other")
        submitted = st.form_submit_button("Сохранить товар", type="primary")
    if not submitted:
        return None
    return validate_product(sku, {
        "name": name, "stock": stock, "cost_price": cost, "current_price": price,
        "ozon_commission_pct": commission, "acquiring_pct": acquiring,
        "logistics_fbo": logistics, "min_margin_pct": margin,
        "storage_per_unit": storage, "advertising_per_unit": advertising,
        "return_cost_per_unit": returns, "other_costs_per_unit": other,
        "target_competitor_sku": competitor_sku, "target_competitor_url": competitor_url,
    }, tax_rate)


# First-run setup is deliberately required before exposing the operational dashboard
if not settings.get("onboarding_complete", False):
    st.markdown('<div class="section-kicker">FIRST-TIME SETUP</div>', unsafe_allow_html=True)
    st.title("Первоначальная настройка")
    st.caption("Настройте рабочее пространство. Подключение к Ozon не требуется для работы с каталогом и расчетами.")
    if LEGACY_JSON_PATH.exists():
        st.info(
            f"Найден старый JSON-каталог. При первом запуске он был перенесен в SQLite; "
            f"сейчас доступно товаров: **{len(portfolio['products'])}**. Исходный JSON не изменен."
        )
    else:
        st.info("Каталог пока пуст. Вы сможете добавить товары вручную или импортировать CSV/XLSX.")
    with st.form("first_run_setup"):
        business_name = st.text_input("Название магазина или рабочего пространства", value=settings.get("business_name", ""))
        tax_rate = st.number_input(
            "Расчетная налоговая ставка (доля от цены продажи)", min_value=0.0,
            max_value=0.999999, value=float(settings.get("tax_rate", 0.06)), step=0.01,
            format="%.4f",
        )
        data_mode_label = st.selectbox(
            "Режим источников цен",
            options=["production", "demo"],
            index=0 if settings.get("data_mode", "production") == "production" else 1,
            format_func=lambda value: "Рабочий – без синтетических цен" if value == "production"
            else "Демонстрационный – разрешены помеченные тестовые цены",
        )
        catalog_start_mode = "keep"
        if portfolio["products"]:
            catalog_start_mode = st.radio(
                "Что сделать с перенесенным каталогом?",
                options=["keep", "clear"], horizontal=True,
                format_func=lambda value: "Оставить товары" if value == "keep" else "Начать с пустого каталога",
            )
        st.caption(
            "В обоих режимах каталог и финансовые расчеты работают локально. "
            "Режим demo разрешает создавать симулированные цены для SKU-заглушек COMP-*; "
            "они не участвуют в рекомендациях."
        )
        confirmed = st.checkbox("Я понимаю, что налоговые и расходные параметры нужно проверить под свой бизнес.")
        submitted = st.form_submit_button("Сохранить настройки и открыть приложение", type="primary")
    if submitted:
        if not confirmed:
            st.error("Подтвердите, что проверите финансовые параметры.")
        else:
            try:
                if catalog_start_mode == "clear":
                    repository.import_products({}, mode="replace", actor="onboarding")
                repository.save_settings({
                    "business_name": business_name.strip(),
                    "tax_rate": tax_rate,
                    "data_mode": data_mode_label,
                    "onboarding_complete": True,
                }, actor="onboarding")
                st.success("Настройки сохранены.")
                st.rerun()
            except (StorageError, ValueError) as exc:
                st.error(str(exc))
    st.stop()

settings = repository.get_settings()
portfolio = repository.load_portfolio()
products = portfolio["products"]
agent = make_agent(portfolio, settings)
observations = observations_for_agent()
analytics = agent.calculate_unit_economics(observations)
queue = build_action_queue(analytics)

header_left, header_right = st.columns([4, 1])
with header_left:
    st.markdown('<div class="section-kicker">SELLER OPERATIONS TOOLKIT</div>', unsafe_allow_html=True)
    st.title("Ozon Smart Agent")
    st.caption("Локальная система анализа экономики ассортимента и поддержки решений продавца.")
with header_right:
    if st.button("Обновить наблюдения", type="primary", use_container_width=True):
        with st.spinner("Получаем доступные наблюдения..."):
            refreshed = agent.collect_competitor_prices()
            repository.save_price_observations(refreshed)
            refreshed_analytics = agent.calculate_unit_economics(refreshed)
            save_recommendation_snapshot(refreshed_analytics)
        st.success("Наблюдения и расчетные рекомендации сохранены в истории.")
        st.rerun()

sections = ["Портфель", "Цены конкурентов", "Каталог и обмен", "История и аудит", "Настройки"]
if st.session_state.get("main_navigation") not in sections:
    st.session_state.main_navigation = "Портфель"
nav_columns = st.columns(len(sections))
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

latest_rows = repository.latest_price_observations()
latest_times = [row["observed_at"] for row in latest_rows.values() if row.get("observed_at")]
last_update = max(latest_times) if latest_times else "еще не обновлялись"
st.caption(
    f"Режим: {'демонстрационный' if settings['data_mode'] == 'demo' else 'рабочий'} · "
    f"Источник внешних цен: публичная страница Ozon (не Seller API) · Последнее обновление: {last_update}"
)

if nav == "Портфель":
    st.markdown('<div class="section-kicker">PORTFOLIO OVERVIEW</div>', unsafe_allow_html=True)
    st.header("Состояние портфеля")
    loss_count = int((analytics["Net Profit"] < 0).sum()) if not analytics.empty else 0
    real_count = int((analytics["Источник цены"] == "real").sum()) if not analytics.empty else 0
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("SKU в каталоге", len(analytics))
    k2.metric("Риск убытка", loss_count, delta="Требует внимания" if loss_count else "Не выявлен",
              delta_color="inverse" if loss_count else "normal")
    k3.metric("SKU в очереди действий", len(queue))
    k4.metric("Реальные ценовые наблюдения", real_count)
    st.caption("Прибыль рассчитывается на одну единицу. Это оценка по введенным параметрам, а не фактическая прибыль Ozon.")
    st.divider()
    st.subheader("Очередь действий")
    if queue.empty:
        st.success("По текущим правилам нет SKU, требующих внимания.")
    else:
        st.dataframe(queue, column_config=money_columns(queue, ["Текущая цена", "Мин. цена"]),
                     use_container_width=True, hide_index=True)
    st.subheader("Экономика товаров")
    if analytics.empty:
        st.info("Каталог пуст. Добавьте товар или импортируйте CSV/XLSX в разделе «Каталог и обмен».")
    else:
        view = analytics[[
            "SKU", "Название товара", "Остаток (шт)", "Текущая цена", "Net Profit", "Маржа, %",
            "ROI, %", "Мин. допустимая цена", "Реком. цена", "Источник цены", "Стратегия",
        ]].copy()
        st.dataframe(
            view,
            column_config={
                **money_columns(view, ["Текущая цена", "Net Profit", "Мин. допустимая цена", "Реком. цена"]),
                "Маржа, %": st.column_config.NumberColumn(format="%.2f %%"),
                "ROI, %": st.column_config.NumberColumn(format="%.2f %%"),
            },
            use_container_width=True,
            hide_index=True,
        )

elif nav == "Цены конкурентов":
    st.markdown('<div class="section-kicker">COMPETITOR PRICE OBSERVATIONS</div>', unsafe_allow_html=True)
    st.header("Цены конкурентов")
    st.caption("Получение внешних наблюдений запускается вручную. Статус real означает успешный разбор публичного ответа, а не независимую проверку цены.")
    if analytics.empty:
        st.info("Добавьте товары и SKU конкурентов в каталоге.")
    else:
        view = analytics[[
            "SKU", "Название товара", "SKU конкурента", "Текущая цена", "Цена конкурента",
            "Источник цены", "Статус данных", "Мин. допустимая цена", "Реком. цена", "Стратегия",
        ]]
        st.dataframe(view, column_config=money_columns(
            view, ["Текущая цена", "Цена конкурента", "Мин. допустимая цена", "Реком. цена"]
        ), use_container_width=True, hide_index=True)
    st.info(
        "Рабочий режим не создает искусственные цены. Если внешний источник недоступен, "
        "наблюдение получает статус unavailable и не используется для ценовой рекомендации."
    )

elif nav == "Каталог и обмен":
    st.markdown('<div class="section-kicker">CATALOG & DATA EXCHANGE</div>', unsafe_allow_html=True)
    st.header("Каталог товаров")
    st.caption("Каталог хранится в SQLite. Изменения валидируются и записываются в журнал аудита.")
    if products:
        for sku, details in products.items():
            with st.expander(f"{sku} · {details['name']}"):
                try:
                    updated = product_editor(sku, details, portfolio["tax_rate"], "edit")
                    if updated is not None:
                        repository.upsert_product(sku, updated)
                        st.success("Товар обновлен.")
                        st.rerun()
                except ConfigurationValidationError as exc:
                    st.error(str(exc))
                if st.button("Удалить товар", key=f"delete_{sku}"):
                    repository.delete_product(sku)
                    st.success("Товар удален. История наблюдений и аудита сохранена.")
                    st.rerun()
    else:
        st.info("Каталог пуст.")

    st.divider()
    st.subheader("Добавить товар")
    with st.form("add_product", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            new_sku = st.text_input("SKU *")
            new_name = st.text_input("Название *")
            new_stock = st.number_input("Остаток, шт.", min_value=0, value=0, step=1)
            new_competitor = st.text_input("SKU конкурента")
            new_url = st.text_input("Ссылка на Ozon")
        with c2:
            new_cost = st.number_input("Себестоимость, ₽", min_value=0.0, value=0.0, step=10.0)
            new_price = st.number_input("Текущая цена, ₽", min_value=0.01, value=100.0, step=10.0)
            new_commission = st.number_input("Комиссия Ozon (доля)", min_value=0.0, max_value=0.999999,
                                             value=0.15, step=0.01, format="%.4f")
            new_acquiring = st.number_input("Эквайринг (доля)", min_value=0.0, max_value=0.999999,
                                            value=0.0, step=0.005, format="%.4f")
            new_margin = st.number_input("Целевая маржа (доля)", min_value=0.0, max_value=0.999999,
                                         value=0.20, step=0.01, format="%.4f")
        with c3:
            new_logistics = st.number_input("Логистика FBO, ₽", min_value=0.0, value=0.0, step=5.0)
            new_storage = st.number_input("Хранение на единицу, ₽", min_value=0.0, value=0.0, step=1.0)
            new_ads = st.number_input("Реклама на единицу, ₽", min_value=0.0, value=0.0, step=1.0)
            new_returns = st.number_input("Возвраты на единицу, ₽", min_value=0.0, value=0.0, step=1.0)
            new_other = st.number_input("Прочие расходы на единицу, ₽", min_value=0.0, value=0.0, step=1.0)
        add = st.form_submit_button("Добавить SKU", type="primary")
    if add:
        try:
            if not new_sku.strip() or new_sku.strip() in products:
                raise ConfigurationValidationError("Укажите уникальный SKU.")
            new_product = validate_product(new_sku.strip(), {
                "name": new_name, "stock": new_stock, "cost_price": new_cost,
                "current_price": new_price, "ozon_commission_pct": new_commission,
                "acquiring_pct": new_acquiring, "logistics_fbo": new_logistics,
                "min_margin_pct": new_margin, "storage_per_unit": new_storage,
                "advertising_per_unit": new_ads, "return_cost_per_unit": new_returns,
                "other_costs_per_unit": new_other, "target_competitor_sku": new_competitor,
                "target_competitor_url": new_url,
            }, portfolio["tax_rate"])
            repository.upsert_product(new_sku.strip(), new_product)
            st.success("Товар добавлен.")
            st.rerun()
        except ConfigurationValidationError as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("Импорт и экспорт")
    products_for_export = repository.list_products()
    export_left, export_right = st.columns(2)
    with export_left:
        st.download_button(
            "Скачать каталог CSV", data=export_catalog_csv(products_for_export),
            file_name="ozon_catalog.csv", mime="text/csv", use_container_width=True,
        )
    with export_right:
        st.download_button(
            "Скачать каталог Excel", data=export_catalog_xlsx(products_for_export),
            file_name="ozon_catalog.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    st.caption("Импорт поддерживает .csv и .xlsx. Используйте заголовки из экспортированного файла; перед записью все строки проходят проверку.")
    uploaded_catalog = st.file_uploader("Выберите CSV или XLSX", type=["csv", "xlsx"], key="catalog_upload")
    import_mode = st.radio(
        "Как обработать загруженные товары?",
        options=["merge", "replace"], horizontal=True,
        format_func=lambda value: "Добавить и обновить совпадающие SKU" if value == "merge"
        else "Полностью заменить текущий каталог",
    )
    replace_confirmed = False
    if import_mode == "replace":
        st.warning("Полная замена удалит из рабочего каталога товары, которых нет в загружаемом файле.")
        replace_confirmed = st.checkbox(
            "Подтверждаю полную замену текущего каталога", key="confirm_catalog_replace"
        )
    import_disabled = uploaded_catalog is None or (import_mode == "replace" and not replace_confirmed)
    if st.button("Проверить и импортировать каталог", disabled=import_disabled):
        try:
            parsed = parse_catalog_upload(uploaded_catalog.name, uploaded_catalog.getvalue(), portfolio["tax_rate"])
            counts = repository.import_products(parsed, mode=import_mode)
            st.success(
                f"Импорт завершен. Добавлено: {counts['created']}; обновлено: {counts['updated']}; "
                f"строк обработано: {counts['total']}."
            )
            st.rerun()
        except (CatalogImportError, ConfigurationValidationError, StorageError) as exc:
            st.error(str(exc))

elif nav == "История и аудит":
    st.markdown('<div class="section-kicker">OBSERVABILITY & DATA INTEGRITY</div>', unsafe_allow_html=True)
    st.header("История и журнал аудита")
    prices_tab, recommendations_tab, audit_tab = st.tabs(["Цены", "Рекомендации", "Аудит изменений"])
    with prices_tab:
        price_history = repository.list_price_history(500)
        if price_history:
            frame = pd.DataFrame(price_history)
            st.dataframe(frame, use_container_width=True, hide_index=True)
        else:
            st.info("История появится после первого ручного обновления наблюдений.")
    with recommendations_tab:
        history = repository.list_recommendation_history(500)
        if history:
            frame = pd.DataFrame(history)
            st.dataframe(frame, column_config=money_columns(
                frame, ["competitor_price", "minimum_price", "recommended_price"]
            ), use_container_width=True, hide_index=True)
        else:
            st.info("История рекомендаций появится после первого обновления цен.")
    with audit_tab:
        audit = repository.list_audit_log(500)
        if audit:
            st.dataframe(pd.DataFrame(audit), use_container_width=True, hide_index=True)
        else:
            st.info("События каталога и настроек будут появляться здесь.")

elif nav == "Настройки":
    st.markdown('<div class="section-kicker">WORKSPACE SETTINGS</div>', unsafe_allow_html=True)
    st.header("Настройки рабочего пространства")
    st.subheader("Бизнес-параметры")
    with st.form("workspace_settings"):
        business_name = st.text_input("Название рабочего пространства", value=settings.get("business_name", ""))
        tax_rate = st.number_input("Расчетная налоговая ставка (доля от цены продажи)", min_value=0.0,
                                   max_value=0.999999, value=float(settings["tax_rate"]), step=0.01, format="%.4f")
        data_mode = st.selectbox(
            "Режим источников", options=["production", "demo"],
            index=0 if settings["data_mode"] == "production" else 1,
            format_func=lambda value: "Рабочий – без синтетических цен" if value == "production"
            else "Демонстрационный – синтетические цены помечаются",
        )
        save_settings = st.form_submit_button("Сохранить настройки", type="primary")
    if save_settings:
        try:
            repository.save_settings({
                "business_name": business_name.strip(),
                "tax_rate": tax_rate,
                "data_mode": data_mode,
                "onboarding_complete": True,
            })
            st.success("Настройки сохранены и записаны в журнал аудита.")
            st.rerun()
        except (StorageError, ValueError) as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("Резервное копирование")
    st.caption("Резервная копия включает каталог, настройки, историю цен, рекомендации и журнал аудита.")
    if st.button("Подготовить резервную копию", type="secondary"):
        try:
            st.session_state["backup_payload"] = repository.backup_bytes()
            st.session_state["backup_filename"] = f"ozon-smart-agent-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
        except StorageError as exc:
            st.error(str(exc))
    if st.session_state.get("backup_payload"):
        st.download_button(
            "Скачать резервную копию SQLite",
            data=st.session_state["backup_payload"],
            file_name=st.session_state["backup_filename"],
            mime="application/vnd.sqlite3",
            use_container_width=True,
        )

    st.subheader("Восстановление из резервной копии")
    backup_upload = st.file_uploader("Выберите файл резервной копии .sqlite3", type=["sqlite3", "db"],
                                     key="backup_upload")
    restore_confirm = st.checkbox("Я понимаю, что восстановление заменит текущую базу данных.")
    if st.button("Восстановить базу", disabled=backup_upload is None or not restore_confirm):
        try:
            safety_backup = repository.restore_from_bytes(backup_upload.getvalue())
            st.cache_resource.clear()
            st.success(
                "База восстановлена. Перед восстановлением создана дополнительная копия: "
                f"{safety_backup if safety_backup else 'не требовалась'}."
            )
            st.rerun()
        except StorageError as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("Среда и источники")
    st.write(f"**Среда:** `{os.getenv('APP_ENV', 'local')}`")
    st.write(f"**Режим данных:** `{settings['data_mode']}`")
    st.write(f"**База данных:** `{DATABASE_PATH}`")
    st.write(f"**Таймаут HTTP:** `{os.getenv('OZON_REQUEST_TIMEOUT', '4')} сек.`")
    st.write(f"**Повторные попытки:** `{os.getenv('OZON_RETRY_TOTAL', '2')}`")
    st.write(f"**TTL кэша цен:** `{agent.cache_ttl} сек.`")
    st.info(
        "Каталог, финансовые расчеты, импорт/экспорт и история работают локально без подключения к Ozon. "
        "Внешние ценовые наблюдения запрашиваются отдельно и используют публичную страницу Ozon, не Seller API."
    )
