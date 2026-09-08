import logging
from typing import Any, LiteralString, NamedTuple, cast

from neo4j import Driver, ManagedTransaction

logger = logging.getLogger(__name__)

# XML-derived statements only — the annotation form already carries its method.
_UNBOUND_STATEMENTS = """
MATCH (s:SqlStatement)
WHERE NOT ( ()-[:EXECUTES]->(s) )
RETURN s.id AS id, s.mapper_qn AS mapper_qn, s.statement_id AS statement_id
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


class MyBatisResolver:
    """Binds each XML-derived `SqlStatement` to the `@Mapper` interface method
    it implements — `(:CodeEntity)-[:EXECUTES]->(:SqlStatement)` — by matching
    the mapper `namespace` + statement `id` to a method whose declaring type is
    that namespace (FQN, or simple-name fallback) and whose name is that id.
    An ambiguous or missing match is left unbound.
    """

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def resolve(self) -> dict[str, int]:
        with self._driver.session() as session:
            result = session.execute_write(self._rebuild)
        logger.info("mybatis graph resolved: %s", result)
        return result

    @classmethod
    def _rebuild(cls, tx: ManagedTransaction) -> dict[str, int]:
        statements = [dict(row) for row in tx.run(cast(LiteralString, _UNBOUND_STATEMENTS))]
        if not statements:
            return {"unbound": 0, "bound": 0}
        methods = [dict(row) for row in tx.run(cast(LiteralString, _MAPPER_METHODS))]
        assembled = cls._assemble(statements, methods)
        if assembled.executes:
            tx.run(cast(LiteralString, _MERGE_EXECUTES), pairs=assembled.executes)
        return {"unbound": len(statements), "bound": len(assembled.executes)}

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
