from typing import Any, LiteralString, NamedTuple, cast

from neo4j import ManagedTransaction

from .graph_resolver import GraphResolver

# XML-derived statements only — the annotation form already carries its method.
# All of them: the EXECUTES edges below are cleared and rebuilt every run (like
# the camel / aop / service-call resolvers), so a renamed / moved `@Mapper`
# method does not strand its old edge on the previous `CodeEntity`.
_XML_STATEMENTS = """
MATCH (s:SqlStatement {origin: 'mybatis-xml'})
RETURN s.id AS id, s.mapper_qn AS mapper_qn, s.statement_id AS statement_id
"""

_CLEAR_XML_EXECUTES = """
MATCH (:CodeEntity)-[r:EXECUTES]->(:SqlStatement {origin: 'mybatis-xml'})
DELETE r
"""

_MAPPER_METHODS = """
MATCH (m:CodeEntity)
WHERE m.kind = 'method'
RETURN m.qualified_name AS qn, m.name AS name, m.parent_qualified_name AS owner
"""

_MERGE_EXECUTES = """
UNWIND $pairs AS pair
MATCH (m:CodeEntity {qualified_name: pair.method})
MATCH (s:SqlStatement {id: pair.stmt})
MERGE (m)-[:EXECUTES]->(s)
"""


class _Assembled(NamedTuple):
    executes: list[dict[str, str]]


class MyBatisResolver(GraphResolver):
    """Binds each XML-derived `SqlStatement` to the `@Mapper` interface method
    it implements — `(:CodeEntity)-[:EXECUTES]->(:SqlStatement)` — by matching
    the mapper `namespace` + statement `id` to a method whose declaring type is
    that namespace (FQN, or simple-name fallback) and whose name is that id.
    An ambiguous or missing match is left unbound.
    """

    _log_label = "mybatis"

    @classmethod
    def _rebuild(cls, tx: ManagedTransaction) -> dict[str, int]:
        statements = [dict(row) for row in tx.run(cast(LiteralString, _XML_STATEMENTS))]
        tx.run(cast(LiteralString, _CLEAR_XML_EXECUTES))
        if not statements:
            return {"xml_statements": 0, "bound": 0}
        methods = [dict(row) for row in tx.run(cast(LiteralString, _MAPPER_METHODS))]
        assembled = cls._assemble(statements, methods)
        if assembled.executes:
            tx.run(cast(LiteralString, _MERGE_EXECUTES), pairs=assembled.executes)
        return {"xml_statements": len(statements), "bound": len(assembled.executes)}

    # -- assembly (pure — unit-tested without Neo4j) --

    @classmethod
    def _assemble(
        cls, statements: list[dict[str, Any]], methods: list[dict[str, Any]]
    ) -> _Assembled:
        by_name: dict[str, list[dict[str, Any]]] = {}
        for method in methods:
            by_name.setdefault(method["name"], []).append(method)

        executes: list[dict[str, str]] = []
        for statement in statements:
            mapper_qn = statement.get("mapper_qn") or ""
            mapper_simple = cls._simple_name(mapper_qn)
            candidates = [
                method
                for method in by_name.get(statement.get("statement_id") or "", [])
                if method.get("owner") == mapper_qn
                or cls._simple_name(method.get("owner") or "") == mapper_simple
            ]
            if len(candidates) == 1:
                executes.append({"method": candidates[0]["qn"], "stmt": statement["id"]})
        return _Assembled(executes)

    @staticmethod
    def _simple_name(qualified_name: str) -> str:
        return qualified_name.rsplit(".", 1)[-1]
