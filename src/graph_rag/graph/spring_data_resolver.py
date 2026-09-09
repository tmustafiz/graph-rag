from typing import Any, LiteralString, NamedTuple, cast

from neo4j import ManagedTransaction

from .graph_resolver import GraphResolver

_CLEAR_LABELS = """
MATCH (n:CodeEntity)
WHERE n:Repository OR n:JpaEntity
REMOVE n:Repository, n:JpaEntity
SET n.repository_base = null, n.repository_entity_type = null, n.repository_id_type = null,
    n.repository_reactive = null, n.jpa_kind = null, n.jpa_table = null
"""
_CLEAR_METHOD_TAGS = """
MATCH (m:CodeEntity)
WHERE m.query_kind IS NOT NULL
SET m.query_kind = null, m.query_text = null, m.query_properties = null
"""
_CLEAR_EDGES = "MATCH ()-[r:MANAGES|PERSISTS_AS|RELATES_TO]->() DELETE r"

_REPO_DEFS = """
MATCH (d:SpringDataRepoDef)
RETURN d.qualified_name AS qualified_name, d.base AS base, d.entity_type AS entity_type,
       d.id_type AS id_type, d.reactive AS reactive, d.method_qns AS method_qns,
       d.method_query_kinds AS method_query_kinds, d.method_query_texts AS method_query_texts,
       d.method_properties AS method_properties
"""
_ENTITY_DEFS = """
MATCH (d:JpaEntityDef)
RETURN d.qualified_name AS qualified_name, d.simple_name AS simple_name, d.kind AS kind,
       d.table AS table, d.association_fields AS association_fields,
       d.association_targets AS association_targets, d.association_kinds AS association_kinds,
       d.association_mapped_by AS association_mapped_by
"""
_CODE_ENTITIES = """
MATCH (c:CodeEntity)
WHERE c.kind IN ['class', 'interface', 'enum', 'record']
RETURN c.qualified_name AS qualified_name, c.name AS name
"""
_DB_TABLES = "MATCH (t:DbTable) RETURN t.qualified_name AS qualified_name, t.name AS name"

_MARK_REPOS = """
UNWIND $rows AS row
MATCH (r:CodeEntity {qualified_name: row.qualified_name})
SET r:Repository, r.repository_base = row.base, r.repository_entity_type = row.entity_type,
    r.repository_id_type = row.id_type, r.repository_reactive = row.reactive
"""
_MARK_ENTITIES = """
UNWIND $rows AS row
MATCH (e:CodeEntity {qualified_name: row.qualified_name})
SET e:JpaEntity, e.jpa_kind = row.kind, e.jpa_table = row.table
"""
_MARK_METHODS = """
UNWIND $rows AS row
MATCH (m:CodeEntity {qualified_name: row.qualified_name})
SET m.query_kind = row.query_kind, m.query_text = row.query_text,
    m.query_properties = row.query_properties
"""
_MERGE_MANAGES = """
UNWIND $rows AS row
MATCH (r:CodeEntity {qualified_name: row.repo})
MATCH (e:CodeEntity {qualified_name: row.entity})
MERGE (r)-[:MANAGES]->(e)
"""
_MERGE_PERSISTS_AS = """
UNWIND $rows AS row
MATCH (e:CodeEntity {qualified_name: row.entity})
MATCH (t:DbTable {qualified_name: row.table_qn})
MERGE (e)-[:PERSISTS_AS]->(t)
"""
_MERGE_RELATES_TO = """
UNWIND $rows AS row
MATCH (a:CodeEntity {qualified_name: row.from})
MATCH (b:CodeEntity {qualified_name: row.to})
MERGE (a)-[rel:RELATES_TO {field: row.field}]->(b)
SET rel.kind = row.kind, rel.mapped_by = row.mapped_by
"""


class _Assembled(NamedTuple):
    repo_marks: list[dict[str, Any]]
    entity_marks: list[dict[str, Any]]
    method_marks: list[dict[str, Any]]
    manages: list[dict[str, str]]
    persists_as: list[dict[str, str]]
    relates_to: list[dict[str, str]]


class SpringDataResolver(GraphResolver):
    """Fourth post-directory-ingest pass (after `SpringXmlResolver`). Projects
    the `SpringDataRepoDef` / `JpaEntityDef` intermediate nodes that
    `SpringDataExtractor` wrote onto the `CodeEntity` graph.

    * A repository interface's `CodeEntity` is tagged `:Repository` with
      `repository_base` / `repository_entity_type` / `repository_id_type` /
      `repository_reactive`; a `(:Repository)-[:MANAGES]->(:JpaEntity)` edge is
      wired when the managed type resolves to an ingested entity.
    * Each declared repository method `CodeEntity` gets `query_kind`
      (`derived` / `jpql` / `native` / `modifying` / `procedure` / `inherited`),
      `query_text` and `query_properties`.
    * A JPA type's `CodeEntity` is tagged `:JpaEntity` with `jpa_kind` /
      `jpa_table`; `(:JpaEntity)-[:PERSISTS_AS]->(:DbTable)` is wired when a
      `DbTable` with that name was ingested (the SQL-schema bridge), and each
      `@OneToMany` / `@ManyToOne` / … becomes
      `(:JpaEntity)-[:RELATES_TO {kind, mapped_by, field}]->(:JpaEntity)`.

    Rebuilt from scratch each run (labels, method tags, and
    `MANAGES` / `PERSISTS_AS` / `RELATES_TO` edges are cleared first), so it is
    idempotent.
    """

    _log_label = "spring data / jpa"

    @classmethod
    def _rebuild(cls, tx: ManagedTransaction) -> dict[str, int]:
        tx.run(cast(LiteralString, _CLEAR_LABELS))
        tx.run(cast(LiteralString, _CLEAR_METHOD_TAGS))
        tx.run(cast(LiteralString, _CLEAR_EDGES))
        assembled = cls._assemble(
            [dict(row) for row in tx.run(cast(LiteralString, _REPO_DEFS))],
            [dict(row) for row in tx.run(cast(LiteralString, _ENTITY_DEFS))],
            [dict(row) for row in tx.run(cast(LiteralString, _CODE_ENTITIES))],
            [dict(row) for row in tx.run(cast(LiteralString, _DB_TABLES))],
        )
        if assembled.repo_marks:
            tx.run(cast(LiteralString, _MARK_REPOS), rows=assembled.repo_marks)
        if assembled.entity_marks:
            tx.run(cast(LiteralString, _MARK_ENTITIES), rows=assembled.entity_marks)
        if assembled.method_marks:
            tx.run(cast(LiteralString, _MARK_METHODS), rows=assembled.method_marks)
        if assembled.manages:
            tx.run(cast(LiteralString, _MERGE_MANAGES), rows=assembled.manages)
        if assembled.persists_as:
            tx.run(cast(LiteralString, _MERGE_PERSISTS_AS), rows=assembled.persists_as)
        if assembled.relates_to:
            tx.run(cast(LiteralString, _MERGE_RELATES_TO), rows=assembled.relates_to)
        return {
            "repositories": len(assembled.repo_marks),
            "jpa_entities": len(assembled.entity_marks),
            "query_methods": len(assembled.method_marks),
            "manages": len(assembled.manages),
            "persists_as": len(assembled.persists_as),
            "relates_to": len(assembled.relates_to),
        }

    # -- assembly (pure — unit-tested without Neo4j) --

    @classmethod
    def _assemble(
        cls,
        repo_defs: list[dict[str, Any]],
        entity_defs: list[dict[str, Any]],
        code_entities: list[dict[str, Any]],
        db_tables: list[dict[str, Any]],
    ) -> _Assembled:
        all_qns = {row["qualified_name"] for row in code_entities}
        entity_qns = {row["qualified_name"] for row in entity_defs}
        entity_qn_by_simple: dict[str, list[str]] = {}
        for row in entity_defs:
            entity_qn_by_simple.setdefault(row["simple_name"], []).append(row["qualified_name"])
        table_qns_by_name: dict[str, list[str]] = {}
        for row in db_tables:
            if row.get("name"):
                table_qns_by_name.setdefault(row["name"], []).append(row["qualified_name"])

        repo_marks: list[dict[str, Any]] = []
        method_marks: list[dict[str, Any]] = []
        manages: list[dict[str, str]] = []
        for definition in repo_defs:
            repo_qn = definition["qualified_name"]
            repo_marks.append(
                {
                    "qualified_name": repo_qn,
                    "base": definition.get("base"),
                    "entity_type": definition.get("entity_type"),
                    "id_type": definition.get("id_type"),
                    "reactive": bool(definition.get("reactive")),
                }
            )
            entity_qn = cls._resolve(definition.get("entity_type"), entity_qns, entity_qn_by_simple)
            if entity_qn is not None:
                manages.append({"repo": repo_qn, "entity": entity_qn})
            method_marks.extend(cls._method_marks(definition))

        entity_marks: list[dict[str, Any]] = []
        persists_as: list[dict[str, str]] = []
        relates_to: list[dict[str, str]] = []
        for definition in entity_defs:
            entity_qn = definition["qualified_name"]
            entity_marks.append(
                {
                    "qualified_name": entity_qn,
                    "kind": definition.get("kind"),
                    "table": definition.get("table"),
                }
            )
            table_name = definition.get("table")
            candidates = table_qns_by_name.get(table_name or "", [])
            if len(candidates) == 1:
                persists_as.append({"entity": entity_qn, "table_qn": candidates[0]})
            relates_to.extend(
                cls._relations(definition, entity_qn, all_qns, entity_qns, entity_qn_by_simple)
            )

        return _Assembled(repo_marks, entity_marks, method_marks, manages, persists_as, relates_to)

    @staticmethod
    def _method_marks(definition: dict[str, Any]) -> list[dict[str, Any]]:
        qns = definition.get("method_qns") or []
        kinds = definition.get("method_query_kinds") or []
        texts = definition.get("method_query_texts") or []
        properties = definition.get("method_properties") or []
        marks: list[dict[str, Any]] = []
        for index, qualified_name in enumerate(qns):
            marks.append(
                {
                    "qualified_name": qualified_name,
                    "query_kind": kinds[index] if index < len(kinds) else "derived",
                    "query_text": texts[index] if index < len(texts) else "",
                    "query_properties": properties[index] if index < len(properties) else "",
                }
            )
        return marks

    @classmethod
    def _relations(
        cls,
        definition: dict[str, Any],
        entity_qn: str,
        all_qns: set[str],
        entity_qns: set[str],
        entity_qn_by_simple: dict[str, list[str]],
    ) -> list[dict[str, str]]:
        fields = definition.get("association_fields") or []
        targets = definition.get("association_targets") or []
        kinds = definition.get("association_kinds") or []
        mapped_by = definition.get("association_mapped_by") or []
        relations: list[dict[str, str]] = []
        for index, field in enumerate(fields):
            raw_target = targets[index] if index < len(targets) else ""
            target_qn = cls._resolve(raw_target, entity_qns, entity_qn_by_simple) or cls._resolve(
                raw_target, all_qns, {}
            )
            if target_qn is None:
                # a self-edge (target == entity) is kept: tree / hierarchy
                # models (Category.parent / .children) need it, and the
                # RELATES_TO {field} key already separates the two directions
                continue
            relations.append(
                {
                    "from": entity_qn,
                    "to": target_qn,
                    "field": field,
                    "kind": kinds[index] if index < len(kinds) else "",
                    "mapped_by": mapped_by[index] if index < len(mapped_by) else "",
                }
            )
        return relations

    @staticmethod
    def _resolve(raw: str | None, exact: set[str], by_simple: dict[str, list[str]]) -> str | None:
        if not raw:
            return None
        if raw in exact:
            return raw
        simple = raw.rsplit(".", 1)[-1].split("<", 1)[0].strip()
        if simple in exact:
            return simple
        candidates = by_simple.get(simple, [])
        return candidates[0] if len(candidates) == 1 else None
