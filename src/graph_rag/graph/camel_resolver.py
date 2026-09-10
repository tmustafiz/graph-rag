from typing import Any, LiteralString, NamedTuple, cast

from neo4j import ManagedTransaction

from .graph_resolver import GraphResolver

_STEPS_WITH_REF = """
MATCH (st:CamelStep)
WHERE st.ref IS NOT NULL
RETURN st.id AS id, st.ref AS ref
"""

_ENTITIES = """
MATCH (c:CodeEntity)
WHERE c.kind IN ['class', 'interface', 'method']
RETURN c.qualified_name AS qn, c.name AS name, c.kind AS kind,
       c.parent_qualified_name AS owner
"""

_BEANS = """
MATCH (c:CodeEntity)-[:IS_BEAN]->(b:Bean)
RETURN b.name AS name, c.qualified_name AS qn
"""

_CLEAR_INVOKES = "MATCH (:CamelStep)-[r:INVOKES]->() DELETE r"

_MERGE_INVOKES = """
UNWIND $pairs AS pair
MATCH (st:CamelStep {id: pair.step})
MATCH (c:CodeEntity {qualified_name: pair.target})
MERGE (st)-[:INVOKES]->(c)
"""


class _Assembled(NamedTuple):
    invokes: list[dict[str, str]]


class CamelResolver(GraphResolver):
    """Post-ingest pass that resolves a Camel `process(...)` / `bean(...)` /
    `to("bean:...")` step's reference to the `CodeEntity` it invokes —
    `(:CamelStep)-[:INVOKES]->(:CodeEntity)`.

    Reference forms, best-effort:

    * `Type.method` → the method whose declaring type's simple name is `Type`
    * `Type` → the class / interface with that simple name
    * `beanName` / `beanName.method` → the `:Bean` with that name, then the
      method on its backing type

    Ambiguous or unresolved references add no edge. Rebuilt each run.
    """

    _log_label = "camel"

    @classmethod
    def _rebuild(cls, tx: ManagedTransaction) -> dict[str, int]:
        steps = [dict(row) for row in tx.run(cast(LiteralString, _STEPS_WITH_REF))]
        tx.run(cast(LiteralString, _CLEAR_INVOKES))
        if not steps:
            return {"steps_with_ref": 0, "invokes": 0}
        entities = [dict(row) for row in tx.run(cast(LiteralString, _ENTITIES))]
        beans = [dict(row) for row in tx.run(cast(LiteralString, _BEANS))]
        assembled = cls._assemble(steps, entities, beans)
        if assembled.invokes:
            tx.run(cast(LiteralString, _MERGE_INVOKES), pairs=assembled.invokes)
        return {"steps_with_ref": len(steps), "invokes": len(assembled.invokes)}

    # -- assembly (pure — unit-tested without Neo4j) --

    @classmethod
    def _assemble(
        cls,
        steps: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        beans: list[dict[str, Any]],
    ) -> _Assembled:
        types_by_simple: dict[str, list[str]] = {}
        methods_by_owner_name: dict[tuple[str, str], list[str]] = {}
        for entity in entities:
            if entity.get("kind") in ("class", "interface"):
                types_by_simple.setdefault(entity["name"], []).append(entity["qn"])
            elif entity.get("kind") == "method":
                owner_simple = cls._simple_name(entity.get("owner") or "")
                methods_by_owner_name.setdefault((owner_simple, entity["name"]), []).append(
                    entity["qn"]
                )
        bean_qn_by_name = {bean["name"]: bean["qn"] for bean in beans}

        invokes: list[dict[str, str]] = []
        for step in steps:
            target = cls._resolve_ref(
                step.get("ref") or "", types_by_simple, methods_by_owner_name, bean_qn_by_name
            )
            if target is not None:
                invokes.append({"step": step["id"], "target": target})
        return _Assembled(invokes)

    @classmethod
    def _resolve_ref(
        cls,
        ref: str,
        types_by_simple: dict[str, list[str]],
        methods_by_owner_name: dict[tuple[str, str], list[str]],
        bean_qn_by_name: dict[str, str],
    ) -> str | None:
        ref = ref.strip()
        if not ref:
            return None
        head, _, member = ref.partition(".")
        if member:
            if head[:1].isupper():
                return cls._unique(methods_by_owner_name.get((head, member), []))
            bean_type = bean_qn_by_name.get(head)
            if bean_type is not None:
                return cls._unique(
                    methods_by_owner_name.get((cls._simple_name(bean_type), member), [])
                )
            return None
        if head[:1].isupper():
            return cls._unique(types_by_simple.get(head, []))
        return bean_qn_by_name.get(head)

    @staticmethod
    def _unique(candidates: list[str]) -> str | None:
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _simple_name(qualified_name: str) -> str:
        return qualified_name.rsplit(".", 1)[-1].rsplit("#", 1)[-1].split("(", 1)[0]
