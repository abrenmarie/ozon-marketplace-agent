import json
import sqlite3

import pytest

from core.analytics import PriceObservation
from core.storage import SQLiteRepository, StorageError

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
}


def make_legacy(path):
    path.write_text(json.dumps({
        "currency": "RUB", "tax_rate": 0.06, "products": {"SKU-01": PRODUCT}
    }), encoding="utf-8")


def test_legacy_json_is_migrated_once_and_original_is_preserved(tmp_path):
    legacy = tmp_path / "portfolio_ozon.json"
    make_legacy(legacy)
    original = legacy.read_text(encoding="utf-8")
    repo = SQLiteRepository(tmp_path / "app.sqlite3", legacy)

    products = repo.list_products()
    assert list(products) == ["SKU-01"]
    assert products["SKU-01"]["acquiring_pct"] == 0.0
    assert repo.get_settings()["tax_rate"] == 0.06
    assert legacy.read_text(encoding="utf-8") == original

    legacy.write_text(json.dumps({"currency": "RUB", "tax_rate": 0.2, "products": {}}), encoding="utf-8")
    repo_again = SQLiteRepository(tmp_path / "app.sqlite3", legacy)
    assert len(repo_again.list_products()) == 1
    assert repo_again.get_settings()["tax_rate"] == 0.06


def test_product_crud_writes_audit_events(tmp_path):
    repo = SQLiteRepository(tmp_path / "app.sqlite3")
    assert repo.upsert_product("SKU-01", PRODUCT) == "created"
    assert repo.upsert_product("SKU-01", PRODUCT | {"stock": 12}) == "updated"
    assert repo.list_products()["SKU-01"]["stock"] == 12
    assert repo.delete_product("SKU-01") is True
    assert repo.delete_product("SKU-01") is False
    actions = [row["action"] for row in repo.list_audit_log()]
    assert actions[:3] == ["product.deleted", "product.updated", "product.created"]


def test_import_merge_and_replace(tmp_path):
    repo = SQLiteRepository(tmp_path / "app.sqlite3")
    repo.upsert_product("SKU-01", PRODUCT)
    counts = repo.import_products({"SKU-01": PRODUCT | {"stock": 14}, "SKU-02": PRODUCT}, mode="merge")
    assert counts == {"created": 1, "updated": 1, "total": 2}
    assert repo.list_products()["SKU-01"]["stock"] == 14
    counts = repo.import_products({"SKU-03": PRODUCT}, mode="replace")
    assert counts["created"] == 1
    assert list(repo.list_products()) == ["SKU-03"]


def test_observation_recommendation_history_and_audit(tmp_path):
    repo = SQLiteRepository(tmp_path / "app.sqlite3")
    repo.upsert_product("SKU-01", PRODUCT)
    observation = PriceObservation(
        price=__import__("decimal").Decimal("1234.50"),
        source="real", status="parsed", competitor_sku="123456",
    )
    assert repo.save_price_observations({"SKU-01": observation}) == 1
    latest = repo.latest_price_observations()["SKU-01"]
    assert latest["price"] == "1234.50"
    repo.save_recommendation(
        sku="SKU-01", competitor_price="1234.50", minimum_price="1000",
        recommended_price="1224.50", strategy="MATCH_COMPETITOR_LOWER",
        rationale="Margin guard passed", data_source="real",
        context={"current_price": 1500, "profit_per_unit": 550, "margin_pct": 36.67},
    )
    assert repo.list_price_history()[0]["product_sku"] == "SKU-01"
    recommendation = repo.list_recommendation_history()[0]
    assert recommendation["strategy"] == "MATCH_COMPETITOR_LOWER"
    assert json.loads(recommendation["context_json"])["current_price"] == 1500


def test_backup_and_restore_recover_catalog_and_history(tmp_path):
    db_path = tmp_path / "app.sqlite3"
    repo = SQLiteRepository(db_path)
    repo.upsert_product("SKU-01", PRODUCT)
    backup = repo.backup_bytes()
    repo.upsert_product("SKU-02", PRODUCT)
    safety_backup = repo.restore_from_bytes(backup)

    assert safety_backup is not None and safety_backup.exists()
    assert list(repo.list_products()) == ["SKU-01"]
    assert repo.list_audit_log()[0]["action"] == "database.restored"


def test_restore_rejects_non_sqlite_payload(tmp_path):
    repo = SQLiteRepository(tmp_path / "app.sqlite3")
    with pytest.raises(StorageError, match="SQLite"):
        repo.restore_from_bytes(b"not a database")


def test_restore_rejects_database_with_wrong_schema(tmp_path):
    repo = SQLiteRepository(tmp_path / "app.sqlite3")
    wrong = tmp_path / "wrong.sqlite3"
    connection = sqlite3.connect(wrong)
    connection.execute("CREATE TABLE something_else(id INTEGER)")
    connection.commit()
    connection.close()
    with pytest.raises(StorageError, match="несовместима"):
        repo.restore_from_bytes(wrong.read_bytes())


def test_latest_observation_uses_last_inserted_row_when_timestamps_match(tmp_path):
    repo = SQLiteRepository(tmp_path / "app.sqlite3")
    repo.upsert_product("SKU-01", PRODUCT)
    first = PriceObservation(
        price=__import__("decimal").Decimal("1200"),
        source="real", status="first", competitor_sku="123456", observed_at="2026-01-01T00:00:00+00:00",
    )
    second = PriceObservation(
        price=__import__("decimal").Decimal("1180"),
        source="real", status="second", competitor_sku="123456", observed_at="2026-01-01T00:00:00+00:00",
    )
    repo.save_price_observations({"SKU-01": first})
    repo.save_price_observations({"SKU-01": second})
    latest = repo.latest_price_observations()["SKU-01"]
    assert latest["status"] == "second"
    assert latest["price"] == "1180"


def test_schema_v1_migrates_recommendation_context_column(tmp_path):
    db_path = tmp_path / "legacy-v1.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        "CREATE TABLE recommendations ("
        "id TEXT PRIMARY KEY, product_sku TEXT NOT NULL, competitor_price TEXT, "
        "minimum_price TEXT, recommended_price TEXT, strategy TEXT NOT NULL, "
        "rationale TEXT NOT NULL, data_source TEXT NOT NULL, created_at TEXT NOT NULL);"
        "PRAGMA user_version=1;"
    )
    connection.commit()
    connection.close()
    repo = SQLiteRepository(db_path)
    with repo.connect() as migrated:
        version = migrated.execute("PRAGMA user_version").fetchone()[0]
        columns = {row[1] for row in migrated.execute("PRAGMA table_info(recommendations)")}
    assert version == 2
    assert "context_json" in columns
