"""SQLite persistence, one-time JSON migration, audit trail, histories and backups"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from domain.validation import ConfigurationValidationError, default_portfolio, validate_portfolio, validate_product

SCHEMA_VERSION = 2
PRODUCT_FIELDS = (
    "name", "stock", "cost_price", "current_price", "ozon_commission_pct", "logistics_fbo",
    "min_margin_pct", "target_competitor_sku", "target_competitor_url", "acquiring_pct",
    "storage_per_unit", "advertising_per_unit", "return_cost_per_unit", "other_costs_per_unit",
)
DEFAULT_SETTINGS: dict[str, Any] = {
    "currency": "RUB",
    "tax_rate": 0.06,
    "data_mode": "production",
    "onboarding_complete": False,
    "business_name": "",
}


class StorageError(RuntimeError):
    """Raised for invalid, incompatible or unavailable local storage operations"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class SQLiteRepository:
    def __init__(self, db_path: str | Path, legacy_json_path: str | Path | None = None):
        self.db_path = Path(db_path).expanduser().resolve()
        self.legacy_json_path = Path(legacy_json_path).expanduser().resolve() if legacy_json_path else None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS products (
            sku TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            stock INTEGER NOT NULL CHECK(stock >= 0),
            cost_price TEXT NOT NULL,
            current_price TEXT NOT NULL,
            ozon_commission_pct TEXT NOT NULL,
            logistics_fbo TEXT NOT NULL,
            min_margin_pct TEXT NOT NULL,
            target_competitor_sku TEXT NOT NULL DEFAULT '',
            target_competitor_url TEXT NOT NULL DEFAULT '',
            acquiring_pct TEXT NOT NULL DEFAULT '0',
            storage_per_unit TEXT NOT NULL DEFAULT '0',
            advertising_per_unit TEXT NOT NULL DEFAULT '0',
            return_cost_per_unit TEXT NOT NULL DEFAULT '0',
            other_costs_per_unit TEXT NOT NULL DEFAULT '0',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_observations (
            id TEXT PRIMARY KEY,
            product_sku TEXT NOT NULL,
            competitor_sku TEXT NOT NULL DEFAULT '',
            price TEXT,
            source TEXT NOT NULL CHECK(source IN ('real','simulated','unavailable')),
            status TEXT NOT NULL,
            observed_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_price_observations_sku_time
            ON price_observations(product_sku, observed_at DESC);
        CREATE TABLE IF NOT EXISTS recommendations (
            id TEXT PRIMARY KEY,
            product_sku TEXT NOT NULL,
            competitor_price TEXT,
            minimum_price TEXT,
            recommended_price TEXT,
            strategy TEXT NOT NULL,
            rationale TEXT NOT NULL,
            data_source TEXT NOT NULL,
            context_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_recommendations_sku_time
            ON recommendations(product_sku, created_at DESC);
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(created_at DESC);
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
        try:
            with self.connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(schema)
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version > SCHEMA_VERSION:
                    raise StorageError(
                        f"База данных имеет более новую версию схемы ({version}); "
                        f"приложение поддерживает {SCHEMA_VERSION}. Обновите приложение."
                    )
                if version < 2:
                    recommendation_columns = {
                        row[1] for row in connection.execute("PRAGMA table_info(recommendations)")
                    }
                    if "context_json" not in recommendation_columns:
                        connection.execute(
                            "ALTER TABLE recommendations ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'"
                        )
                if version < SCHEMA_VERSION:
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                now = utc_now()
                initial_settings = dict(DEFAULT_SETTINGS)
                initial_settings["data_mode"] = os.getenv("DATA_MODE", DEFAULT_SETTINGS["data_mode"]).strip().lower()
                if initial_settings["data_mode"] not in {"demo", "production"}:
                    initial_settings["data_mode"] = DEFAULT_SETTINGS["data_mode"]
                for key, value in initial_settings.items():
                    connection.execute(
                        "INSERT OR IGNORE INTO app_settings(key,value_json,updated_at) VALUES(?,?,?)",
                        (key, _json(value), now),
                    )
                connection.commit()
            self._migrate_legacy_json_once()
        except (sqlite3.Error, OSError) as exc:
            if isinstance(exc, StorageError):
                raise
            raise StorageError(f"Не удалось инициализировать SQLite: {exc}") from exc

    def _migrate_legacy_json_once(self) -> None:
        with self.connect() as connection:
            done = connection.execute(
                "SELECT value FROM app_meta WHERE key='legacy_json_migrated'"
            ).fetchone()
            if done:
                return
            if self.legacy_json_path and self.legacy_json_path.exists():
                try:
                    legacy = json.loads(self.legacy_json_path.read_text(encoding="utf-8"))
                    normalized = validate_portfolio(legacy)
                except (OSError, json.JSONDecodeError, ConfigurationValidationError) as exc:
                    raise StorageError(
                        "Не удалось перенести старый JSON-каталог в SQLite. "
                        "Исходный JSON оставлен без изменений. Проверьте файл data/portfolio_ozon.json: "
                        f"{exc}"
                    ) from exc
                existing_count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
                if existing_count == 0 and normalized["products"]:
                    self._insert_products(connection, normalized["products"])
                    self._set_setting(connection, "currency", normalized["currency"])
                    self._set_setting(connection, "tax_rate", normalized["tax_rate"])
                    self._audit(
                        connection, action="legacy_json_migrated", entity_type="catalog",
                        entity_id="all", actor="system", before=None,
                        after={"product_count": len(normalized["products"]),
                               "source": str(self.legacy_json_path)},
                    )
            connection.execute(
                "INSERT INTO app_meta(key,value) VALUES('legacy_json_migrated','1')"
            )
            connection.commit()

    @staticmethod
    def _set_setting(connection: sqlite3.Connection, key: str, value: Any) -> None:
        connection.execute(
            "INSERT INTO app_settings(key,value_json,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
            (key, _json(value), utc_now()),
        )

    @staticmethod
    def _audit(connection: sqlite3.Connection, *, action: str, entity_type: str,
               entity_id: str, actor: str, before: Any, after: Any) -> None:
        connection.execute(
            "INSERT INTO audit_log(id,action,entity_type,entity_id,actor,before_json,after_json,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), action, entity_type, entity_id, actor,
             _json(before) if before is not None else None,
             _json(after) if after is not None else None, utc_now()),
        )

    @staticmethod
    def _insert_products(connection: sqlite3.Connection, products: Mapping[str, Mapping[str, Any]]) -> None:
        now = utc_now()
        fields = ",".join(PRODUCT_FIELDS)
        placeholders = ",".join("?" for _ in PRODUCT_FIELDS)
        query = f"INSERT INTO products(sku,{fields},created_at,updated_at) VALUES(?,{placeholders},?,?)"
        for sku, product in products.items():
            values = [str(product[field]) for field in PRODUCT_FIELDS]
            values[1] = int(product["stock"])
            connection.execute(query, [sku, *values, now, now])

    def get_settings(self) -> dict[str, Any]:
        settings = dict(DEFAULT_SETTINGS)
        with self.connect() as connection:
            for row in connection.execute("SELECT key,value_json FROM app_settings"):
                settings[row["key"]] = json.loads(row["value_json"])
        return settings

    def save_settings(self, updates: Mapping[str, Any], actor: str = "user") -> dict[str, Any]:
        allowed = set(DEFAULT_SETTINGS)
        unknown = set(updates) - allowed
        if unknown:
            raise StorageError(f"Неизвестные настройки: {', '.join(sorted(unknown))}")
        current = self.get_settings()
        candidate = {**current, **updates}
        if candidate["data_mode"] not in {"demo", "production"}:
            raise StorageError("Режим данных должен быть demo или production.")
        tax = float(candidate["tax_rate"])
        if not 0 <= tax < 1:
            raise StorageError("Налоговая ставка должна быть от 0 до 1.")
        if "tax_rate" in updates:
            try:
                validate_portfolio({
                    "currency": candidate["currency"],
                    "tax_rate": tax,
                    "products": self.list_products(),
                })
            except ConfigurationValidationError as exc:
                raise StorageError(
                    f"Нельзя сохранить налоговую ставку: для одного или нескольких SKU "
                    f"комиссия, эквайринг, налог и целевая маржа становятся несовместимы. {exc}"
                ) from exc
        with self.connect() as connection:
            for key, value in updates.items():
                self._set_setting(connection, key, value)
            self._audit(connection, action="settings.updated", entity_type="settings",
                        entity_id="workspace", actor=actor, before=current,
                        after=candidate)
            connection.commit()
        return candidate

    def load_portfolio(self) -> dict[str, Any]:
        settings = self.get_settings()
        return {
            "currency": settings["currency"],
            "tax_rate": settings["tax_rate"],
            "products": self.list_products(),
        }

    def list_products(self) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT sku,{','.join(PRODUCT_FIELDS)} FROM products ORDER BY sku"
            ).fetchall()
        products: dict[str, dict[str, Any]] = {}
        for row in rows:
            product = dict(row)
            sku = product.pop("sku")
            product["stock"] = int(product["stock"])
            for key in PRODUCT_FIELDS:
                if key != "name" and key != "stock" and key not in {
                    "target_competitor_sku", "target_competitor_url"
                }:
                    product[key] = float(product[key])
            products[sku] = product
        return products

    def upsert_product(self, sku: str, product: Mapping[str, Any], actor: str = "user") -> str:
        settings = self.get_settings()
        normalized = validate_product(sku, product, settings["tax_rate"])
        with self.connect() as connection:
            existing_row = connection.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
            before = dict(existing_row) if existing_row else None
            now = utc_now()
            columns = ",".join(PRODUCT_FIELDS)
            placeholders = ",".join("?" for _ in PRODUCT_FIELDS)
            updates = ",".join(f"{field}=excluded.{field}" for field in PRODUCT_FIELDS)
            query = (
                f"INSERT INTO products(sku,{columns},created_at,updated_at) "
                f"VALUES(?,{placeholders},?,?) ON CONFLICT(sku) DO UPDATE SET "
                f"{updates},updated_at=excluded.updated_at"
            )
            values = [normalized[field] for field in PRODUCT_FIELDS]
            connection.execute(query, [sku, *values, now, now])
            self._audit(connection, action="product.updated" if before else "product.created",
                        entity_type="product", entity_id=sku, actor=actor,
                        before=before, after={"sku": sku, **normalized})
            connection.commit()
        return "updated" if before else "created"

    def delete_product(self, sku: str, actor: str = "user") -> bool:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM products WHERE sku=?", (sku,))
            self._audit(connection, action="product.deleted", entity_type="product",
                        entity_id=sku, actor=actor, before=dict(row), after=None)
            connection.commit()
        return True

    def import_products(self, products: Mapping[str, Mapping[str, Any]], *, mode: str,
                        actor: str = "import") -> dict[str, int]:
        if mode not in {"merge", "replace"}:
            raise StorageError("Режим импорта должен быть merge или replace.")
        settings = self.get_settings()
        normalized = validate_portfolio({
            "currency": settings["currency"], "tax_rate": settings["tax_rate"],
            "products": products,
        })["products"]
        counts = {"created": 0, "updated": 0, "total": len(normalized)}
        with self.connect() as connection:
            if mode == "replace":
                connection.execute("DELETE FROM products")
                self._insert_products(connection, normalized)
                counts["created"] = len(normalized)
            else:
                for sku, product in normalized.items():
                    exists = connection.execute("SELECT 1 FROM products WHERE sku=?", (sku,)).fetchone()
                    if exists:
                        counts["updated"] += 1
                        now = utc_now()
                        assignments = ",".join(f"{field}=?" for field in PRODUCT_FIELDS)
                        connection.execute(
                            f"UPDATE products SET {assignments},updated_at=? WHERE sku=?",
                            [*[product[field] for field in PRODUCT_FIELDS], now, sku],
                        )
                    else:
                        counts["created"] += 1
                        self._insert_products(connection, {sku: product})
            self._audit(connection, action=f"catalog.import.{mode}", entity_type="catalog",
                        entity_id="all", actor=actor, before=None, after=counts)
            connection.commit()
        return counts

    def save_price_observations(self, observations: Mapping[str, Any]) -> int:
        now = utc_now()
        with self.connect() as connection:
            for sku, observation in observations.items():
                price = observation.price
                connection.execute(
                    "INSERT INTO price_observations(id,product_sku,competitor_sku,price,source,status,observed_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), sku, observation.competitor_sku,
                     str(price) if price is not None else None,
                     observation.source, observation.status,
                     getattr(observation, "observed_at", "") or now),
                )
            self._audit(connection, action="prices.refreshed", entity_type="price_observations",
                        entity_id="all", actor="system", before=None,
                        after={"count": len(observations), "observed_at": now})
            connection.commit()
        return len(observations)

    def save_recommendation(self, *, sku: str, competitor_price: Any, minimum_price: Any,
                            recommended_price: Any, strategy: str, rationale: str,
                            data_source: str, context: Mapping[str, Any] | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO recommendations(id,product_sku,competitor_price,minimum_price,"
                "recommended_price,strategy,rationale,data_source,context_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), sku,
                 str(competitor_price) if competitor_price is not None else None,
                 str(minimum_price) if minimum_price is not None else None,
                 str(recommended_price) if recommended_price is not None else None,
                 strategy, rationale, data_source, _json(context or {}), utc_now()),
            )
            connection.commit()

    def latest_price_observations(self) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT p.* FROM price_observations p "
                "JOIN (SELECT product_sku,MAX(rowid) AS latest_rowid "
                "FROM price_observations GROUP BY product_sku) x "
                "ON p.rowid=x.latest_rowid"
            ).fetchall()
        return {row["product_sku"]: dict(row) for row in rows}

    def list_price_history(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM price_observations ORDER BY observed_at DESC, rowid DESC LIMIT ?",
                (max(1, min(int(limit), 5000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_recommendation_history(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM recommendations ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (max(1, min(int(limit), 5000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_audit_log(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_log ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (max(1, min(int(limit), 5000)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_event(self, action: str, entity_type: str, entity_id: str,
                     before: Any = None, after: Any = None, actor: str = "system") -> None:
        with self.connect() as connection:
            self._audit(connection, action=action, entity_type=entity_type,
                        entity_id=entity_id, actor=actor, before=before, after=after)
            connection.commit()

    def backup_to_path(self, destination: str | Path) -> Path:
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target == self.db_path:
            raise StorageError("Путь резервной копии не может совпадать с рабочей базой.")
        try:
            with self.connect() as source:
                target_connection = sqlite3.connect(target)
                try:
                    source.backup(target_connection)
                    integrity = target_connection.execute("PRAGMA quick_check").fetchone()[0]
                    if integrity != "ok":
                        raise StorageError(f"Проверка резервной копии не пройдена: {integrity}")
                finally:
                    target_connection.close()
            return target
        except (sqlite3.Error, OSError) as exc:
            raise StorageError(f"Не удалось создать резервную копию: {exc}") from exc

    def backup_bytes(self) -> bytes:
        with tempfile.TemporaryDirectory(prefix="ozon-backup-") as directory:
            target = Path(directory) / "ozon_smart_agent.sqlite3"
            self.backup_to_path(target)
            return target.read_bytes()

    def restore_from_bytes(self, payload: bytes) -> Path | None:
        if not payload or not payload.startswith(b"SQLite format 3\x00"):
            raise StorageError("Файл не является корректной SQLite-базой данных.")
        temp_path: Path | None = None
        try:
            handle = tempfile.NamedTemporaryFile(
                prefix=".restore_", suffix=".sqlite3", dir=self.db_path.parent, delete=False
            )
            temp_path = Path(handle.name)
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            candidate = sqlite3.connect(f"file:{temp_path}?mode=ro", uri=True)
            try:
                integrity = candidate.execute("PRAGMA quick_check").fetchone()[0]
                version = int(candidate.execute("PRAGMA user_version").fetchone()[0])
                tables = {row[0] for row in candidate.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                required = {"products", "app_settings", "price_observations", "recommendations", "audit_log"}
                if integrity != "ok" or version != SCHEMA_VERSION or not required.issubset(tables):
                    raise StorageError("Резервная копия повреждена или несовместима с текущей версией.")
            finally:
                candidate.close()
            safety_backup = None
            if self.db_path.exists():
                backup_dir = self.db_path.parent / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                safety_backup = backup_dir / (
                    f"before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite3"
                )
                self.backup_to_path(safety_backup)

            # Copy through SQLite's backup API instead of replacing the database file
            # This keeps WAL/SHM sidecars consistent with the restored database
            with sqlite3.connect(f"file:{temp_path}?mode=ro", uri=True) as source:
                with self.connect() as destination:
                    source.backup(destination)

            self.record_event("database.restored", "database", "workspace",
                              after={"safety_backup": str(safety_backup) if safety_backup else None})
            return safety_backup
        except (sqlite3.Error, OSError) as exc:
            if isinstance(exc, StorageError):
                raise
            raise StorageError(f"Не удалось восстановить базу данных: {exc}") from exc
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
