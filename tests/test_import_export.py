from core.import_export import (
    CatalogImportError,
    export_catalog_csv,
    export_catalog_xlsx,
    parse_catalog_upload,
)

PRODUCT = {
    "name": "Тестовый товар",
    "stock": 10,
    "cost_price": 500,
    "current_price": 1500,
    "ozon_commission_pct": 0.15,
    "logistics_fbo": 100,
    "min_margin_pct": 0.20,
    "target_competitor_sku": "COMP-TEST",
    "target_competitor_url": "",
    "acquiring_pct": 0.01,
    "storage_per_unit": 3,
    "advertising_per_unit": 7,
    "return_cost_per_unit": 2,
    "other_costs_per_unit": 4,
}


def test_csv_export_import_round_trip():
    payload = export_catalog_csv({"SKU-01": PRODUCT})
    imported = parse_catalog_upload("catalog.csv", payload, 0.06)
    assert imported["SKU-01"]["name"] == PRODUCT["name"]
    assert imported["SKU-01"]["acquiring_pct"] == 0.01
    assert imported["SKU-01"]["other_costs_per_unit"] == 4


def test_xlsx_export_import_round_trip():
    payload = export_catalog_xlsx({"SKU-01": PRODUCT})
    imported = parse_catalog_upload("catalog.xlsx", payload, 0.06)
    assert imported["SKU-01"]["stock"] == 10
    assert imported["SKU-01"]["advertising_per_unit"] == 7


def test_import_accepts_russian_headers():
    payload = (
        "Артикул;Название;Остаток;Себестоимость;Текущая цена;Комиссия Ozon;Логистика FBO;Минимальная маржа\n"
        "SKU-02;Товар;5;100;300;0.15;20;0.2\n"
    ).encode("utf-8-sig")
    imported = parse_catalog_upload("catalog.csv", payload, 0.06)
    assert imported["SKU-02"]["current_price"] == 300


def test_import_rejects_duplicate_skus():
    payload = export_catalog_csv({"SKU-01": PRODUCT})
    text = payload.decode("utf-8-sig")
    payload = (text + text.splitlines()[1] + "\n").encode("utf-8-sig")
    try:
        parse_catalog_upload("catalog.csv", payload, 0.06)
    except CatalogImportError as exc:
        assert "повторяется SKU" in str(exc)
    else:
        raise AssertionError("Duplicate SKU should be rejected")


def test_import_rejects_unknown_extension():
    try:
        parse_catalog_upload("catalog.xls", b"", 0.06)
    except CatalogImportError as exc:
        assert "только" in str(exc)
    else:
        raise AssertionError("Unsupported file extension should be rejected")


def test_csv_export_uses_excel_friendly_separator_and_formula_safe_text():
    risky = PRODUCT | {"name": "=HYPERLINK(\"https://example.com\",\"open\")"}
    payload = export_catalog_csv({"SKU-01": risky})
    text = payload.decode("utf-8-sig")
    assert ";" in text.splitlines()[0]
    assert "'=HYPERLINK" in text
    imported = parse_catalog_upload("safe.csv", payload, 0.06)
    assert imported["SKU-01"]["name"].startswith("'")


def test_xlsx_export_sanitizes_formula_like_text():
    risky = PRODUCT | {"name": "=1+1"}
    payload = export_catalog_xlsx({"SKU-01": risky})
    imported = parse_catalog_upload("safe.xlsx", payload, 0.06)
    assert imported["SKU-01"]["name"] == "'=1+1"
