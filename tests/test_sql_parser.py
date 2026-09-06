import builtins
import logging
from pathlib import Path

import pytest

from graph_rag.ingest.parsers.sql_parser import SqlParser


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body)
    return path


def _tables(document) -> dict[str, object]:
    return {table.qualified_name: table for table in document.db_tables}


def _columns(document) -> dict[str, object]:
    return {column.qualified_name: column for column in document.db_columns}


def test_can_handle_matches_sql_extension_case_insensitively() -> None:
    parser = SqlParser()
    assert parser.can_handle(Path("migrations/V1__init.sql"))
    assert parser.can_handle(Path("SCHEMA.SQL"))
    assert not parser.can_handle(Path("query.txt"))
    assert not parser.can_handle(Path("app.py"))


def test_table_columns_carry_type_nullability_and_primary_key(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "schema.sql",
        "CREATE TABLE sales.customer (\n"
        "  id INTEGER PRIMARY KEY,\n"
        "  email VARCHAR(255) NOT NULL,\n"
        "  nickname TEXT,\n"
        "  created_at TIMESTAMP DEFAULT now()\n"
        ");\n",
    )

    document = SqlParser().parse(path)

    table = _tables(document)["sales.customer"]
    assert table.name == "customer"
    assert table.schema_name == "sales"
    assert table.file_path == str(path)

    columns = _columns(document)
    identifier = columns["sales.customer.id"]
    assert identifier.data_type == "INT"
    assert identifier.primary_key is True
    assert identifier.nullable is False  # PRIMARY KEY implies NOT NULL

    email = columns["sales.customer.email"]
    assert email.nullable is False
    assert email.primary_key is False

    assert columns["sales.customer.nickname"].nullable is True
    assert columns["sales.customer.created_at"].default is not None


def test_has_column_pairs_link_every_column_to_its_table(tmp_path: Path) -> None:
    path = _write(tmp_path, "t.sql", "CREATE TABLE app.item (id INT PRIMARY KEY, label TEXT);\n")

    document = SqlParser().parse(path)

    assert {column.qualified_name for column in document.db_columns} == {
        "app.item.id",
        "app.item.label",
    }
    assert all(column.table_qualified_name == "app.item" for column in document.db_columns)


def test_inline_foreign_key_becomes_column_and_table_references(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "schema.sql",
        "CREATE TABLE app.region (id INT PRIMARY KEY);\n"
        "CREATE TABLE app.customer (\n"
        "  id INT PRIMARY KEY,\n"
        "  region_id INT REFERENCES app.region (id)\n"
        ");\n",
    )

    document = SqlParser().parse(path)

    assert _columns(document)["app.customer.region_id"].references == ["app.region.id"]
    assert _tables(document)["app.customer"].references == ["app.region"]


def test_table_level_and_alter_table_foreign_keys_resolve(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "schema.sql",
        "CREATE TABLE app.customer (id INT PRIMARY KEY);\n"
        "CREATE TABLE app.region (id INT PRIMARY KEY);\n"
        "CREATE TABLE app.orders (\n"
        "  id BIGINT PRIMARY KEY,\n"
        "  customer_id INT,\n"
        "  region_id INT,\n"
        "  CONSTRAINT fk_customer FOREIGN KEY (customer_id) REFERENCES app.customer (id)\n"
        ");\n"
        "ALTER TABLE app.orders\n"
        "  ADD CONSTRAINT fk_region FOREIGN KEY (region_id) REFERENCES app.region (id);\n",
    )

    document = SqlParser().parse(path)

    columns = _columns(document)
    assert columns["app.orders.customer_id"].references == ["app.customer.id"]
    assert columns["app.orders.region_id"].references == ["app.region.id"]
    assert _tables(document)["app.orders"].references == ["app.customer", "app.region"]


def test_alter_in_a_separate_file_emits_standalone_references(tmp_path: Path) -> None:
    # A migration file that only alters a table created by an earlier migration.
    path = _write(
        tmp_path,
        "003_fk.sql",
        "ALTER TABLE sales.orders\n"
        "  ADD CONSTRAINT fk_orders_region"
        " FOREIGN KEY (region_id) REFERENCES sales.region (id);\n",
    )

    document = SqlParser().parse(path)

    assert document.db_tables == []
    assert document.db_columns == []
    levels = {
        (ref.level, ref.from_qualified_name, ref.to_qualified_name)
        for ref in document.db_references
    }
    assert ("column", "sales.orders.region_id", "sales.region.id") in levels
    assert ("table", "sales.orders", "sales.region") in levels


def test_view_depends_on_its_selected_tables_excluding_ctes(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "schema.sql",
        "CREATE TABLE app.orders (id INT PRIMARY KEY, total NUMERIC);\n"
        "CREATE TABLE app.customer (id INT PRIMARY KEY, email TEXT);\n"
        "CREATE VIEW app.v_open AS\n"
        "  WITH recent AS (SELECT * FROM app.orders WHERE total > 0)\n"
        "  SELECT r.id, c.email FROM recent r JOIN app.customer c ON c.id = r.id;\n",
    )

    document = SqlParser().parse(path)

    view = document.db_views[0]
    assert view.qualified_name == "app.v_open"
    assert view.materialized is False
    assert sorted(view.depends_on) == ["app.customer", "app.orders"]


def test_materialized_view_is_flagged(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "schema.sql",
        "-- grag:dialect=postgres\n"
        "CREATE TABLE app.event (id INT PRIMARY KEY);\n"
        "CREATE MATERIALIZED VIEW app.mv_event AS SELECT id FROM app.event;\n",
    )

    document = SqlParser().parse(path)

    assert document.db_views[0].materialized is True


def test_index_captures_covered_columns_and_uniqueness(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "schema.sql",
        "CREATE TABLE app.orders (id INT PRIMARY KEY, customer_id INT, total NUMERIC);\n"
        "CREATE UNIQUE INDEX idx_orders_customer ON app.orders (customer_id, total);\n",
    )

    document = SqlParser().parse(path)

    index = document.db_indexes[0]
    assert index.qualified_name == "app.orders.idx_orders_customer"
    assert index.table_qualified_name == "app.orders"
    assert index.columns == ["customer_id", "total"]
    assert index.unique is True


def test_postgres_and_tsql_dialects_both_parse(tmp_path: Path) -> None:
    postgres = _write(
        tmp_path,
        "pg.sql",
        "-- grag:dialect=postgres\n"
        'CREATE TABLE "app"."order" (\n'
        '  "id" bigserial PRIMARY KEY,\n'
        '  "payload" jsonb NOT NULL\n'
        ");\n",
    )
    tsql = _write(
        tmp_path,
        "ms.sql",
        "-- grag:dialect=tsql\n"
        "CREATE TABLE [app].[Order] (\n"
        "  [Id] BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,\n"
        "  [Payload] NVARCHAR(MAX) NOT NULL\n"
        ");\n",
    )

    pg_document = SqlParser().parse(postgres)
    ms_document = SqlParser().parse(tsql)

    assert _tables(pg_document)["app.order"].schema_name == "app"
    assert _columns(pg_document)["app.order.payload"].data_type == "JSONB"

    assert _tables(ms_document)["app.Order"].schema_name == "app"
    assert _columns(ms_document)["app.Order.Id"].primary_key is True


def test_unknown_dialect_falls_back_to_generic_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(
        tmp_path,
        "schema.sql",
        "-- grag:dialect=klingon\nCREATE TABLE app.thing (id INT PRIMARY KEY);\n",
    )

    with caplog.at_level(logging.WARNING):
        document = SqlParser().parse(path)

    assert "app.thing" in _tables(document)
    assert any("klingon" in record.message for record in caplog.records)


def test_unparseable_file_yields_empty_source_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write(tmp_path, "broken.sql", "CREATE TABLE (((\nthis is not sql;\n")

    with caplog.at_level(logging.WARNING):
        document = SqlParser().parse(path)

    assert document.source.source_type == "sql"
    assert document.source.path == str(path)
    assert document.db_tables == []
    assert document.db_columns == []
    assert document.db_views == []
    assert document.db_indexes == []
    assert any("could not parse" in record.message for record in caplog.records)


def test_parse_without_sqlglot_raises_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, "schema.sql", "CREATE TABLE app.thing (id INT PRIMARY KEY);\n")
    real_import = builtins.__import__

    def _no_sqlglot(name: str, *args, **kwargs):
        if name == "sqlglot" or name.startswith("sqlglot."):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_sqlglot)

    with pytest.raises(RuntimeError, match=r"'sql' extra"):
        SqlParser().parse(path)
