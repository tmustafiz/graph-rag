from typing import LiteralString, cast

from neo4j import Driver, ManagedTransaction

from graph_rag.ingest.models import ParsedDocument

_BATCH_SIZE = 500

_MERGE_SOURCE = """
MERGE (s:Source {path: $path})
SET s.type = $type, s.content_hash = $content_hash,
    s.ingested_at = $ingested_at, s.version = $version
"""

_MERGE_SECTIONS = """
UNWIND $sections AS row
MERGE (sec:Section {id: row.id})
SET sec.title = row.title, sec.level = row.level, sec.breadcrumb = row.breadcrumb,
    sec.order = row.order, sec.start_page = row.start_page, sec.end_page = row.end_page
WITH sec, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:HAS_SECTION]->(sec)
WITH sec, row
FOREACH (_ IN CASE WHEN row.parent_id IS NOT NULL THEN [1] ELSE [] END |
    MERGE (parent:Section {id: row.parent_id})
    MERGE (parent)-[:PARENT_OF]->(sec)
)
"""

_MERGE_CHUNKS = """
UNWIND $chunks AS row
MERGE (c:Chunk {id: row.id})
SET c.text = row.text, c.token_count = row.token_count, c.content_hash = row.content_hash,
    c.start_page = row.start_page, c.end_page = row.end_page, c.embedding = row.embedding
WITH c, row
MATCH (sec:Section {id: row.section_id})
MERGE (sec)-[:HAS_CHUNK]->(c)
"""

_MERGE_NEXT = """
UNWIND $pairs AS pair
MATCH (a:Chunk {id: pair.from}), (b:Chunk {id: pair.to})
MERGE (a)-[:NEXT]->(b)
"""

_MERGE_CODE_ENTITIES = """
UNWIND $entities AS row
MERGE (e:CodeEntity {qualified_name: row.qualified_name})
SET e.name = row.name, e.kind = row.kind, e.language = row.language,
    e.embed_text = row.embed_text,
    e.file_path = row.file_path, e.start_line = row.start_line, e.end_line = row.end_line,
    e.signature = row.signature, e.docstring = row.docstring, e.embedding = row.embedding
WITH e, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(e)
WITH e, row
FOREACH (_ IN CASE WHEN row.parent_qualified_name IS NOT NULL THEN [1] ELSE [] END |
    MERGE (parent:CodeEntity {qualified_name: row.parent_qualified_name})
    MERGE (parent)-[:CONTAINS]->(e)
)
"""

_MERGE_CALLS = """
UNWIND $pairs AS pair
MATCH (caller:CodeEntity {qualified_name: pair.from})
MERGE (callee:CodeEntity {qualified_name: pair.to})
MERGE (caller)-[:CALLS]->(callee)
"""

_MERGE_IMPORTS = """
UNWIND $pairs AS pair
MATCH (importer:CodeEntity {qualified_name: pair.from})
MERGE (imported:CodeEntity {qualified_name: pair.to})
MERGE (importer)-[:IMPORTS]->(imported)
"""

_MERGE_RENDERS = """
UNWIND $pairs AS pair
MATCH (parent:CodeEntity {qualified_name: pair.from})
MERGE (child:CodeEntity {qualified_name: pair.to})
MERGE (parent)-[:RENDERS]->(child)
"""

_MERGE_READS = """
UNWIND $pairs AS pair
MATCH (routine:CodeEntity {qualified_name: pair.from})
MERGE (t:DbTable {qualified_name: pair.to})
MERGE (routine)-[:READS]->(t)
"""

_MERGE_WRITES = """
UNWIND $pairs AS pair
MATCH (routine:CodeEntity {qualified_name: pair.from})
MERGE (t:DbTable {qualified_name: pair.to})
MERGE (routine)-[:WRITES]->(t)
"""

_MERGE_TRIGGER_ON = """
UNWIND $pairs AS pair
MATCH (trigger:CodeEntity {qualified_name: pair.from})
MERGE (t:DbTable {qualified_name: pair.to})
MERGE (trigger)-[:ON]->(t)
"""

_MERGE_DB_TABLES = """
UNWIND $rows AS row
MERGE (t:DbTable {qualified_name: row.qualified_name})
SET t.name = row.name, t.schema_name = row.schema_name, t.file_path = row.file_path,
    t.embed_text = row.embed_text, t.embedding = row.embedding
WITH t, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(t)
"""

_MERGE_DB_COLUMNS = """
UNWIND $rows AS row
MERGE (col:DbColumn {qualified_name: row.qualified_name})
SET col.name = row.name, col.table_qualified_name = row.table_qualified_name,
    col.data_type = row.data_type, col.nullable = row.nullable,
    col.default = row.default, col.primary_key = row.primary_key
WITH col, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(col)
WITH col, row
MATCH (t:DbTable {qualified_name: row.table_qualified_name})
MERGE (t)-[:HAS_COLUMN]->(col)
"""

_MERGE_DB_VIEWS = """
UNWIND $rows AS row
MERGE (v:DbView {qualified_name: row.qualified_name})
SET v.name = row.name, v.schema_name = row.schema_name, v.materialized = row.materialized,
    v.file_path = row.file_path, v.embed_text = row.embed_text, v.embedding = row.embedding
WITH v, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(v)
"""

_MERGE_DB_INDEXES = """
UNWIND $rows AS row
MERGE (ix:DbIndex {qualified_name: row.qualified_name})
SET ix.name = row.name, ix.table_qualified_name = row.table_qualified_name,
    ix.columns = row.columns, ix.unique = row.unique
WITH ix, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(ix)
WITH ix, row
MATCH (t:DbTable {qualified_name: row.table_qualified_name})
MERGE (t)-[:HAS_INDEX]->(ix)
"""

_MERGE_COLUMN_REFERENCES = """
UNWIND $pairs AS pair
MATCH (col:DbColumn {qualified_name: pair.from})
MERGE (target:DbColumn {qualified_name: pair.to})
MERGE (col)-[:REFERENCES]->(target)
"""

_MERGE_TABLE_REFERENCES = """
UNWIND $pairs AS pair
MATCH (t:DbTable {qualified_name: pair.from})
MERGE (target:DbTable {qualified_name: pair.to})
MERGE (t)-[:REFERENCES]->(target)
"""

_MERGE_VIEW_DEPENDS_ON = """
UNWIND $pairs AS pair
MATCH (v:DbView {qualified_name: pair.from})
MERGE (target:DbTable {qualified_name: pair.to})
MERGE (v)-[:DEPENDS_ON]->(target)
"""

_MERGE_POLICY_RULES = """
UNWIND $rules AS row
MERGE (p:PolicyRule {id: row.id})
SET p.name = row.name, p.category = row.category, p.severity = row.severity,
    p.guideline = row.guideline, p.provider = row.provider, p.file_path = row.file_path,
    p.embed_text = row.embed_text, p.embedding = row.embedding
WITH p, row
MATCH (src:Source {path: $source_path})
MERGE (src)-[:DEFINES]->(p)
"""

_MERGE_APPLIES_TO = """
UNWIND $pairs AS pair
MATCH (p:PolicyRule {id: pair.from})
MERGE (c:Concept {name: pair.to})
SET c.type = "resource_type"
MERGE (p)-[:APPLIES_TO]->(c)
"""

_GET_SOURCE_CONTENT_HASH = """
MATCH (s:Source {path: $path})
RETURN s.content_hash AS content_hash
"""

# Reconciliation deletes stale children a Source no longer produces on
# re-parse (e.g. a deleted function, a removed heading) — run after every
# write so an updated Source never leaves orphaned graph state behind.
# Chunks are reconciled before Sections so a stale Section is never left
# holding chunks that were already removed by its own query.
_RECONCILE_CHUNKS = """
MATCH (:Source {path: $source_path})-[:HAS_SECTION]->(:Section)-[:HAS_CHUNK]->(c:Chunk)
WHERE NOT c.id IN $keep_ids
DETACH DELETE c
"""

_RECONCILE_SECTIONS = """
MATCH (:Source {path: $source_path})-[:HAS_SECTION]->(sec:Section)
WHERE NOT sec.id IN $keep_ids
DETACH DELETE sec
"""

_RECONCILE_CODE_ENTITIES = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(e:CodeEntity)
WHERE NOT e.qualified_name IN $keep_ids
DETACH DELETE e
"""

_RECONCILE_POLICY_RULES = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(p:PolicyRule)
WHERE NOT p.id IN $keep_ids
DETACH DELETE p
"""

# One reconcile per `:Db*` label — a re-parsed migration file that no longer
# produces a table / column / view / index leaves no orphan behind.
_RECONCILE_DB_TABLES = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(n:DbTable)
WHERE NOT n.qualified_name IN $keep_ids
DETACH DELETE n
"""

_RECONCILE_DB_COLUMNS = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(n:DbColumn)
WHERE NOT n.qualified_name IN $keep_ids
DETACH DELETE n
"""

_RECONCILE_DB_VIEWS = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(n:DbView)
WHERE NOT n.qualified_name IN $keep_ids
DETACH DELETE n
"""

_RECONCILE_DB_INDEXES = """
MATCH (:Source {path: $source_path})-[:DEFINES]->(n:DbIndex)
WHERE NOT n.qualified_name IN $keep_ids
DETACH DELETE n
"""


class GraphWriter:
    """Idempotently upserts a `ParsedDocument` into Neo4j."""

    def __init__(self, driver: Driver) -> None:
        self._driver = driver

    def write(self, document: ParsedDocument) -> None:
        with self._driver.session() as session:
            session.execute_write(self._write_source, document)
            for batch in self._batched([s.model_dump(mode="json") for s in document.sections]):
                session.execute_write(self._write_sections, document.source.path, batch)
            for batch in self._batched([c.model_dump(mode="json") for c in document.chunks]):
                session.execute_write(self._write_chunks, batch)
            for batch in self._batched(self._chunk_pairs(document)):
                session.execute_write(self._write_next, batch)
            for batch in self._batched([e.model_dump(mode="json") for e in document.code_entities]):
                session.execute_write(self._write_code_entities, document.source.path, batch)
            for batch in self._batched(self._call_pairs(document)):
                session.execute_write(self._write_calls, batch)
            for batch in self._batched(self._import_pairs(document)):
                session.execute_write(self._write_imports, batch)
            for batch in self._batched(self._render_pairs(document)):
                session.execute_write(self._write_renders, batch)
            for batch in self._batched([t.model_dump(mode="json") for t in document.db_tables]):
                session.execute_write(self._write_db_tables, document.source.path, batch)
            for batch in self._batched([c.model_dump(mode="json") for c in document.db_columns]):
                session.execute_write(self._write_db_columns, document.source.path, batch)
            for batch in self._batched([v.model_dump(mode="json") for v in document.db_views]):
                session.execute_write(self._write_db_views, document.source.path, batch)
            for batch in self._batched([i.model_dump(mode="json") for i in document.db_indexes]):
                session.execute_write(self._write_db_indexes, document.source.path, batch)
            for batch in self._batched(self._column_reference_pairs(document)):
                session.execute_write(self._write_column_references, batch)
            for batch in self._batched(self._table_reference_pairs(document)):
                session.execute_write(self._write_table_references, batch)
            for batch in self._batched(self._view_depends_on_pairs(document)):
                session.execute_write(self._write_view_depends_on, batch)
            for batch in self._batched(self._reads_pairs(document)):
                session.execute_write(self._write_reads, batch)
            for batch in self._batched(self._writes_pairs(document)):
                session.execute_write(self._write_writes, batch)
            for batch in self._batched(self._trigger_on_pairs(document)):
                session.execute_write(self._write_trigger_on, batch)
            for batch in self._batched([r.model_dump(mode="json") for r in document.policy_rules]):
                session.execute_write(self._write_policy_rules, document.source.path, batch)
            for batch in self._batched(self._applies_to_pairs(document)):
                session.execute_write(self._write_applies_to, batch)
            session.execute_write(
                self._reconcile_chunks,
                document.source.path,
                [c.id for c in document.chunks],
            )
            session.execute_write(
                self._reconcile_sections,
                document.source.path,
                [s.id for s in document.sections],
            )
            session.execute_write(
                self._reconcile_code_entities,
                document.source.path,
                [e.qualified_name for e in document.code_entities],
            )
            session.execute_write(
                self._reconcile_policy_rules,
                document.source.path,
                [r.id for r in document.policy_rules],
            )
            session.execute_write(
                self._reconcile_db_tables,
                document.source.path,
                [t.qualified_name for t in document.db_tables],
            )
            session.execute_write(
                self._reconcile_db_columns,
                document.source.path,
                [c.qualified_name for c in document.db_columns],
            )
            session.execute_write(
                self._reconcile_db_views,
                document.source.path,
                [v.qualified_name for v in document.db_views],
            )
            session.execute_write(
                self._reconcile_db_indexes,
                document.source.path,
                [i.qualified_name for i in document.db_indexes],
            )

    def get_source_content_hash(self, path: str) -> str | None:
        """The `content_hash` currently stored for a `Source`, or `None` if unseen."""
        with self._driver.session() as session:
            record = session.run(cast(LiteralString, _GET_SOURCE_CONTENT_HASH), path=path).single()
            return record["content_hash"] if record else None

    @staticmethod
    def _write_source(tx: ManagedTransaction, document: ParsedDocument) -> None:
        tx.run(
            cast(LiteralString, _MERGE_SOURCE),
            path=document.source.path,
            type=document.source.source_type,
            content_hash=document.source.content_hash,
            ingested_at=document.source.ingested_at.isoformat(),
            version=document.source.version,
        )

    @staticmethod
    def _write_sections(tx: ManagedTransaction, source_path: str, sections: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_SECTIONS), sections=sections, source_path=source_path)

    @staticmethod
    def _write_chunks(tx: ManagedTransaction, chunks: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_CHUNKS), chunks=chunks)

    @staticmethod
    def _write_next(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_NEXT), pairs=pairs)

    @staticmethod
    def _write_code_entities(
        tx: ManagedTransaction, source_path: str, entities: list[dict]
    ) -> None:
        tx.run(
            cast(LiteralString, _MERGE_CODE_ENTITIES), entities=entities, source_path=source_path
        )

    @staticmethod
    def _write_calls(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_CALLS), pairs=pairs)

    @staticmethod
    def _write_imports(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_IMPORTS), pairs=pairs)

    @staticmethod
    def _write_renders(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_RENDERS), pairs=pairs)

    @staticmethod
    def _write_reads(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_READS), pairs=pairs)

    @staticmethod
    def _write_writes(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_WRITES), pairs=pairs)

    @staticmethod
    def _write_trigger_on(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_TRIGGER_ON), pairs=pairs)

    @staticmethod
    def _write_db_tables(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_DB_TABLES), rows=rows, source_path=source_path)

    @staticmethod
    def _write_db_columns(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_DB_COLUMNS), rows=rows, source_path=source_path)

    @staticmethod
    def _write_db_views(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_DB_VIEWS), rows=rows, source_path=source_path)

    @staticmethod
    def _write_db_indexes(tx: ManagedTransaction, source_path: str, rows: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_DB_INDEXES), rows=rows, source_path=source_path)

    @staticmethod
    def _write_column_references(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_COLUMN_REFERENCES), pairs=pairs)

    @staticmethod
    def _write_table_references(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_TABLE_REFERENCES), pairs=pairs)

    @staticmethod
    def _write_view_depends_on(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_VIEW_DEPENDS_ON), pairs=pairs)

    @staticmethod
    def _write_policy_rules(tx: ManagedTransaction, source_path: str, rules: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_POLICY_RULES), rules=rules, source_path=source_path)

    @staticmethod
    def _write_applies_to(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_APPLIES_TO), pairs=pairs)

    @staticmethod
    def _reconcile_chunks(tx: ManagedTransaction, source_path: str, keep_ids: list[str]) -> None:
        tx.run(cast(LiteralString, _RECONCILE_CHUNKS), source_path=source_path, keep_ids=keep_ids)

    @staticmethod
    def _reconcile_sections(tx: ManagedTransaction, source_path: str, keep_ids: list[str]) -> None:
        tx.run(cast(LiteralString, _RECONCILE_SECTIONS), source_path=source_path, keep_ids=keep_ids)

    @staticmethod
    def _reconcile_code_entities(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_CODE_ENTITIES),
            source_path=source_path,
            keep_ids=keep_ids,
        )

    @staticmethod
    def _reconcile_policy_rules(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_POLICY_RULES),
            source_path=source_path,
            keep_ids=keep_ids,
        )

    @staticmethod
    def _reconcile_db_tables(tx: ManagedTransaction, source_path: str, keep_ids: list[str]) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_DB_TABLES), source_path=source_path, keep_ids=keep_ids
        )

    @staticmethod
    def _reconcile_db_columns(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_DB_COLUMNS), source_path=source_path, keep_ids=keep_ids
        )

    @staticmethod
    def _reconcile_db_views(tx: ManagedTransaction, source_path: str, keep_ids: list[str]) -> None:
        tx.run(cast(LiteralString, _RECONCILE_DB_VIEWS), source_path=source_path, keep_ids=keep_ids)

    @staticmethod
    def _reconcile_db_indexes(
        tx: ManagedTransaction, source_path: str, keep_ids: list[str]
    ) -> None:
        tx.run(
            cast(LiteralString, _RECONCILE_DB_INDEXES), source_path=source_path, keep_ids=keep_ids
        )

    @staticmethod
    def _chunk_pairs(document: ParsedDocument) -> list[dict]:
        # section_id embeds a zero-padded index, so this sort is full document reading order.
        ordered = sorted(document.chunks, key=lambda c: (c.section_id, c.order))
        return [{"from": a.id, "to": b.id} for a, b in zip(ordered, ordered[1:], strict=False)]

    @staticmethod
    def _call_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": callee}
            for entity in document.code_entities
            for callee in entity.calls
        ]

    @staticmethod
    def _import_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": imported}
            for entity in document.code_entities
            for imported in entity.imports
        ]

    @staticmethod
    def _render_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": rendered}
            for entity in document.code_entities
            for rendered in entity.renders
        ]

    @staticmethod
    def _column_reference_pairs(document: ParsedDocument) -> list[dict]:
        pairs = [
            {"from": column.qualified_name, "to": target}
            for column in document.db_columns
            for target in column.references
        ]
        pairs.extend(
            {"from": reference.from_qualified_name, "to": reference.to_qualified_name}
            for reference in document.db_references
            if reference.level == "column"
        )
        return pairs

    @staticmethod
    def _table_reference_pairs(document: ParsedDocument) -> list[dict]:
        pairs = [
            {"from": table.qualified_name, "to": target}
            for table in document.db_tables
            for target in table.references
        ]
        pairs.extend(
            {"from": reference.from_qualified_name, "to": reference.to_qualified_name}
            for reference in document.db_references
            if reference.level == "table"
        )
        return pairs

    @staticmethod
    def _view_depends_on_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": view.qualified_name, "to": target}
            for view in document.db_views
            for target in view.depends_on
        ]

    @staticmethod
    def _reads_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": table}
            for entity in document.code_entities
            for table in entity.reads
        ]

    @staticmethod
    def _writes_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": table}
            for entity in document.code_entities
            for table in entity.writes
        ]

    @staticmethod
    def _trigger_on_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": entity.qualified_name, "to": entity.trigger_table}
            for entity in document.code_entities
            if entity.trigger_table
        ]

    @staticmethod
    def _applies_to_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": rule.id, "to": resource_type}
            for rule in document.policy_rules
            for resource_type in rule.resource_types
        ]

    @staticmethod
    def _batched(rows: list) -> list[list]:
        return [rows[i : i + _BATCH_SIZE] for i in range(0, len(rows), _BATCH_SIZE)]
