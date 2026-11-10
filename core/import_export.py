"""Validated CSV/XLSX catalog import and export helpers"""
from __future__ import annotations

import csv
import io
from typing import Any, Mapping

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from domain.validation import ConfigurationValidationError, validate_product

CATALOG_FIELDS = [
    "sku", "name", "stock", "cost_price", "current_price", "ozon_commission_pct",
    "logistics_fbo", "min_margin_pct", "target_competitor_sku", "target_competitor_url",
    "acquiring_pct", "storage_per_unit", "advertising_per_unit", "return_cost_per_unit",
    "other_costs_per_unit",
]
HEADER_ALIASES = {
    "артикул": "sku", "sku продавца": "sku", "название": "name", "название товара": "name",
    "остаток": "stock", "остаток шт": "stock", "себестоимость": "cost_price",
    "текущая цена": "current_price", "комиссия": "ozon_commission_pct",
    "комиссия ozon": "ozon_commission_pct", "логистика fbo": "logistics_fbo",
    "минимальная маржа": "min_margin_pct", "sku конкурента": "target_competitor_sku",
    "ссылка конкурента": "target_competitor_url", "эквайринг": "acquiring_pct",
    "хранение на единицу": "storage_per_unit", "реклама на единицу": "advertising_per_unit",
    "возвраты на единицу": "return_cost_per_unit", "прочие расходы на единицу": "other_costs_per_unit",
}


class CatalogImportError(ValueError):
    """Raised when an uploaded catalog cannot be safely imported"""


def _header_map(header: Any) -> str:
    raw = str(header or "").strip()
    normalized = raw.lower().replace("ё", "е")
    normalized = normalized.replace(",", " ").replace(".", " ").replace(":", " ")
    normalized = " ".join(normalized.split())
    return HEADER_ALIASES.get(normalized, normalized)


def _rows_from_csv(payload: bytes) -> list[dict[str, Any]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CatalogImportError("CSV должен быть сохранен в кодировке UTF-8.") from exc
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise CatalogImportError("В CSV отсутствует строка заголовков.")
    result = []
    for row in reader:
        if not row or all(value in (None, "") for value in row.values()):
            continue
        result.append({_header_map(key): value for key, value in row.items() if key is not None})
    return result


def _rows_from_xlsx(payload: bytes) -> list[dict[str, Any]]:
    try:
        workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    except Exception as exc:
        raise CatalogImportError(f"Не удалось прочитать XLSX: {exc}") from exc
    try:
        sheet = workbook.active
        values = sheet.iter_rows(values_only=True)
        headers = next(values, None)
        if not headers:
            raise CatalogImportError("В Excel-файле отсутствует строка заголовков.")
        mapped = [_header_map(value) for value in headers]
        result = []
        for values_row in values:
            if not values_row or all(value is None for value in values_row):
                continue
            result.append({mapped[i]: values_row[i] for i in range(min(len(mapped), len(values_row)))
                           if mapped[i]})
        return result
    finally:
        workbook.close()


def parse_catalog_upload(filename: str, payload: bytes, tax_rate: Any) -> dict[str, dict[str, Any]]:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "csv":
        rows = _rows_from_csv(payload)
    elif suffix == "xlsx":
        rows = _rows_from_xlsx(payload)
    else:
        raise CatalogImportError("Поддерживаются только файлы .csv и .xlsx.")
    if not rows:
        raise CatalogImportError("Файл не содержит строк с товарами.")

    products: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for line_number, row in enumerate(rows, start=2):
        sku_value = row.get("sku")
        sku = str(sku_value).strip() if sku_value is not None else ""
        if not sku:
            errors.append(f"Строка {line_number}: не указан sku.")
            continue
        if sku in products:
            errors.append(f"Строка {line_number}: повторяется SKU {sku!r}.")
            continue
        product = {field: row.get(field, "") for field in CATALOG_FIELDS if field != "sku"}
        defaults = {
            "stock": 0, "cost_price": 0, "current_price": 0, "ozon_commission_pct": 0,
            "logistics_fbo": 0, "min_margin_pct": 0, "target_competitor_sku": "",
            "target_competitor_url": "", "acquiring_pct": 0, "storage_per_unit": 0,
            "advertising_per_unit": 0, "return_cost_per_unit": 0, "other_costs_per_unit": 0,
        }
        for key, default in defaults.items():
            if product.get(key) in (None, ""):
                product[key] = default
        try:
            products[sku] = validate_product(sku, product, tax_rate)
        except ConfigurationValidationError as exc:
            errors.append(f"Строка {line_number}, SKU {sku}: {exc}")
    if errors:
        preview = "\n".join(errors[:20])
        suffix_text = f"\nИ еще ошибок: {len(errors) - 20}." if len(errors) > 20 else ""
        raise CatalogImportError(f"Импорт отменен: найдены ошибки.\n{preview}{suffix_text}")
    return products


TEXT_FIELDS = {"sku", "name", "target_competitor_sku", "target_competitor_url"}


def _safe_spreadsheet_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    probe = value.lstrip()
    if probe.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def _product_rows(products: Mapping[str, Mapping[str, Any]]) -> list[list[Any]]:
    rows = [CATALOG_FIELDS]
    for sku, product in products.items():
        values = [sku, *[product.get(field, "") for field in CATALOG_FIELDS[1:]]]
        rows.append([
            _safe_spreadsheet_text(value) if field in TEXT_FIELDS else value
            for field, value in zip(CATALOG_FIELDS, values)
        ])
    return rows


def export_catalog_csv(products: Mapping[str, Mapping[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    # Semicolon-delimited UTF-8 BOM CSV opens more predictably in Russian Excel locales
    writer = csv.writer(stream, delimiter=";")
    writer.writerows(_product_rows(products))
    return stream.getvalue().encode("utf-8-sig")


def export_catalog_xlsx(products: Mapping[str, Mapping[str, Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Catalog"
    for row in _product_rows(products):
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="315B9A")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        width = min(max(max(len(str(cell.value or "")) for cell in column) + 2, 12), 36)
        sheet.column_dimensions[column[0].column_letter].width = width
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()
