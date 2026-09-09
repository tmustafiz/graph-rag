"""v0.7.0 code-review regressions in `GraphWriter`'s MERGE / reconcile Cypher
(#156, #157, #158, #165.2). No live Neo4j in the suite — these assert on the
query text and on which statements `_reconcile_message_flow` schedules.
"""

from graph_rag.graph import graph_writer as gw


class _RecordingTx:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def run(self, query: str, **_params: object) -> list:
        self.queries.append(query)
        return []


def test_message_flow_reconcile_is_label_scoped_and_folds_fqn_aliases() -> None:
    """#165.2 — no full-graph `MATCH (n)` sweep. #156 — bare/FQN EventType merge."""
    tx = _RecordingTx()
    gw.GraphWriter._reconcile_message_flow(tx, "x.java", [], [], [], [])  # type: ignore[arg-type]

    assert gw._MERGE_EVENT_TYPE_ALIASES in tx.queries
    assert gw._SWEEP_ORPHAN_EVENT_TYPES in tx.queries
    assert gw._SWEEP_ORPHAN_DESTINATIONS in tx.queries
    assert not hasattr(gw, "_SWEEP_ORPHAN_MESSAGE_NODES")
    for query in (gw._SWEEP_ORPHAN_EVENT_TYPES, gw._SWEEP_ORPHAN_DESTINATIONS):
        assert "MATCH (n)\n" not in query
    # the alias merge re-points both edge directions before deleting the bare node
    assert "PUBLISHES" in gw._MERGE_EVENT_TYPE_ALIASES
    assert "CONSUMED_BY" in gw._MERGE_EVENT_TYPE_ALIASES
    assert "DETACH DELETE bare" in gw._MERGE_EVENT_TYPE_ALIASES


def test_sql_accesses_merges_on_qualified_name_not_name() -> None:
    """#158 — never strand a `qualified_name`-null DbTable."""
    assert "MERGE (t:DbTable {name:" not in gw._MERGE_SQL_ACCESSES
    assert "MERGE (t:DbTable {qualified_name: table_qn})" in gw._MERGE_SQL_ACCESSES
    assert "real.qualified_name IS NOT NULL" in gw._MERGE_SQL_ACCESSES


def test_http_endpoint_merge_rebuilds_a_single_direction_edge() -> None:
    """#157 — an endpoint that flips outbound must not keep both edges, and the
    handler match must be OPTIONAL."""
    assert "DELETE stale_handled, stale_calls" in gw._MERGE_HTTP_ENDPOINTS
    assert "OPTIONAL MATCH (handler:CodeEntity {qualified_name: row.handler_qualified_name})" in (
        gw._MERGE_HTTP_ENDPOINTS
    )
    assert "handler IS NOT NULL" in gw._MERGE_HTTP_ENDPOINTS
