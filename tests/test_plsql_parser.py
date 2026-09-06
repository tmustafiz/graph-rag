import logging
from pathlib import Path

import pytest

from graph_rag.ingest.parsers.sql_parser import SqlParser

_ORACLE_PACKAGE = """-- grag:dialect=oracle
-- Order lifecycle package.
CREATE OR REPLACE PACKAGE sales.order_pkg AS
    PROCEDURE submit(p_id IN NUMBER);
    PROCEDURE publish(p_id IN NUMBER);
    FUNCTION rejected_count RETURN NUMBER;
END order_pkg;
/
CREATE OR REPLACE PACKAGE BODY sales.order_pkg AS
    PROCEDURE submit(p_id IN NUMBER) IS
    BEGIN
        UPDATE sales.orders SET status = 'S' WHERE id = p_id;
        INSERT INTO sales.audit(order_id, action) VALUES (p_id, 'submit');
        publish(p_id);
    END submit;
    PROCEDURE publish(p_id IN NUMBER) IS
    BEGIN
        INSERT INTO sales.outbox(order_id) VALUES (p_id);
    END publish;
    FUNCTION rejected_count RETURN NUMBER IS
        n NUMBER;
    BEGIN
        SELECT COUNT(*) INTO n FROM sales.orders WHERE status = 'R';
        RETURN n;
    END rejected_count;
END order_pkg;
/
CREATE OR REPLACE FUNCTION sales.is_expedited(p_id IN NUMBER) RETURN BOOLEAN IS
    lane VARCHAR2(20);
BEGIN
    SELECT lane INTO lane FROM sales.orders WHERE id = p_id;
    RETURN lane = 'expedited';
END is_expedited;
/
CREATE OR REPLACE TRIGGER sales.trg_orders_audit
AFTER INSERT ON sales.orders
FOR EACH ROW
BEGIN
    INSERT INTO sales.audit(order_id) VALUES (:new.id);
END;
/
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body)
    return path


def _by_qualified_name(document) -> dict[str, object]:
    return {entity.qualified_name: entity for entity in document.code_entities}


def test_oracle_package_spec_and_body_fold_into_one_entity_per_routine(tmp_path: Path) -> None:
    document = SqlParser().parse(_write(tmp_path, "order_pkg.sql", _ORACLE_PACKAGE))
    by_name = _by_qualified_name(document)

    assert by_name["sales.order_pkg"].kind == "package"
    assert by_name["sales.order_pkg"].docstring == "Order lifecycle package."

    submit = by_name["sales.order_pkg.submit"]
    assert submit.kind == "procedure"
    assert submit.parent_qualified_name == "sales.order_pkg"
    assert "p_id IN NUMBER" in submit.signature

    # Each packaged routine appears exactly once (spec declaration + body
    # definition folded together).
    assert [qn for qn in by_name].count("sales.order_pkg.submit") == 1
    assert sum(e.qualified_name == "sales.order_pkg.submit" for e in document.code_entities) == 1


def test_oracle_call_graph_and_table_access_edges(tmp_path: Path) -> None:
    document = SqlParser().parse(_write(tmp_path, "order_pkg.sql", _ORACLE_PACKAGE))
    by_name = _by_qualified_name(document)

    submit = by_name["sales.order_pkg.submit"]
    assert submit.calls == ["sales.order_pkg.publish"]
    assert set(submit.writes) == {"sales.orders", "sales.audit"}

    assert by_name["sales.order_pkg.publish"].writes == ["sales.outbox"]
    assert by_name["sales.order_pkg.rejected_count"].reads == ["sales.orders"]
    assert by_name["sales.is_expedited"].reads == ["sales.orders"]


def test_oracle_trigger_has_on_and_writes(tmp_path: Path) -> None:
    document = SqlParser().parse(_write(tmp_path, "order_pkg.sql", _ORACLE_PACKAGE))
    trigger = _by_qualified_name(document)["sales.trg_orders_audit"]

    assert trigger.kind == "trigger"
    assert trigger.trigger_table == "sales.orders"
    assert trigger.writes == ["sales.audit"]


def test_graph_writer_pairs_include_reads_writes_and_trigger_on(tmp_path: Path) -> None:
    from graph_rag.graph.graph_writer import GraphWriter

    document = SqlParser().parse(_write(tmp_path, "order_pkg.sql", _ORACLE_PACKAGE))

    writes = {(pair["from"], pair["to"]) for pair in GraphWriter._writes_pairs(document)}
    reads = {(pair["from"], pair["to"]) for pair in GraphWriter._reads_pairs(document)}
    on_pairs = {(pair["from"], pair["to"]) for pair in GraphWriter._trigger_on_pairs(document)}

    assert ("sales.order_pkg.submit", "sales.orders") in writes
    assert ("sales.order_pkg.rejected_count", "sales.orders") in reads
    assert ("sales.trg_orders_audit", "sales.orders") in on_pairs


def test_plpgsql_function_header_exact_and_body_swept(tmp_path: Path) -> None:
    body = (
        "-- grag:dialect=postgres\n"
        "CREATE FUNCTION sales.expedite(p_order_id bigint) RETURNS integer AS $$\n"
        "BEGIN\n"
        "    UPDATE sales.orders SET lane = 'expedited' WHERE id = p_order_id;\n"
        "    INSERT INTO sales.audit(order_id) SELECT id FROM sales.orders WHERE id = p_order_id;\n"
        "    PERFORM sales.notify_ops(p_order_id);\n"
        "    RETURN 1;\n"
        "END; $$ LANGUAGE plpgsql;\n"
        "CREATE FUNCTION sales.notify_ops(p_order_id bigint) RETURNS void AS $$\n"
        "BEGIN\n"
        "    INSERT INTO sales.ops_queue(order_id) VALUES (p_order_id);\n"
        "END; $$ LANGUAGE plpgsql;\n"
    )
    document = SqlParser().parse(_write(tmp_path, "functions.sql", body))
    by_name = _by_qualified_name(document)

    expedite = by_name["sales.expedite"]
    assert expedite.kind == "function"
    assert "p_order_id BIGINT" in expedite.signature
    assert "RETURNS INT" in expedite.signature
    assert expedite.calls == ["sales.notify_ops"]
    assert set(expedite.writes) == {"sales.orders", "sales.audit"}
    assert by_name["sales.notify_ops"].writes == ["sales.ops_queue"]


def test_tsql_procedure_body_is_analyzed_via_ast(tmp_path: Path) -> None:
    body = (
        "-- grag:dialect=tsql\n"
        "CREATE PROCEDURE dbo.sync_orders @since DATE AS\n"
        "BEGIN\n"
        "    INSERT INTO dbo.audit (msg) SELECT name FROM dbo.staging WHERE created > @since;\n"
        "    UPDATE dbo.orders SET synced = 1 WHERE placed_at > @since;\n"
        "    DELETE FROM dbo.scratch;\n"
        "    EXEC dbo.recompute_totals @since;\n"
        "END\n"
        "GO\n"
        "CREATE PROCEDURE dbo.recompute_totals @since DATE AS\n"
        "BEGIN\n"
        "    UPDATE dbo.orders SET total = 0;\n"
        "END\n"
    )
    document = SqlParser().parse(_write(tmp_path, "procs.sql", body))
    by_name = _by_qualified_name(document)

    sync = by_name["dbo.sync_orders"]
    assert sync.kind == "procedure"
    assert sync.calls == ["dbo.recompute_totals"]
    assert set(sync.writes) == {"dbo.audit", "dbo.orders", "dbo.scratch"}
    assert sync.reads == ["dbo.staging"]


def test_schema_and_procedures_coexist_in_one_file(tmp_path: Path) -> None:
    body = (
        "-- grag:dialect=postgres\n"
        "CREATE TABLE sales.orders (id bigint PRIMARY KEY, lane text);\n"
        "CREATE FUNCTION sales.touch(p_id bigint) RETURNS void AS $$\n"
        "BEGIN UPDATE sales.orders SET lane = 'x' WHERE id = p_id; END; $$ LANGUAGE plpgsql;\n"
    )
    document = SqlParser().parse(_write(tmp_path, "mixed.sql", body))

    assert {table.qualified_name for table in document.db_tables} == {"sales.orders"}
    assert _by_qualified_name(document)["sales.touch"].writes == ["sales.orders"]


def test_unanalyzable_body_yields_header_only_entity_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    body = (
        "-- grag:dialect=oracle\n"
        "CREATE OR REPLACE PROCEDURE sales.mystery @@@ garbage tokens no keyword\n"
        "BEGIN NULL; END;\n"
        "/\n"
    )
    with caplog.at_level(logging.WARNING):
        document = SqlParser().parse(_write(tmp_path, "mystery.prc", body))

    mystery = _by_qualified_name(document)["sales.mystery"]
    assert mystery.kind == "procedure"
    assert mystery.calls == []
    assert mystery.reads == []
    assert mystery.writes == []
    assert any("could not analyze the body" in record.message for record in caplog.records)


def test_can_handle_covers_oracle_object_extensions() -> None:
    parser = SqlParser()
    for name in ("pkg.pks", "pkg.pkb", "load.prc", "calc.fnc", "audit.trg", "logic.plsql"):
        assert parser.can_handle(Path(name))
