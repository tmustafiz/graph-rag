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
SET e.name = row.name, e.kind = row.kind, e.embed_text = row.embed_text,
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
            for batch in self._batched([r.model_dump(mode="json") for r in document.policy_rules]):
                session.execute_write(self._write_policy_rules, document.source.path, batch)
            for batch in self._batched(self._applies_to_pairs(document)):
                session.execute_write(self._write_applies_to, batch)

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
    def _write_policy_rules(tx: ManagedTransaction, source_path: str, rules: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_POLICY_RULES), rules=rules, source_path=source_path)

    @staticmethod
    def _write_applies_to(tx: ManagedTransaction, pairs: list[dict]) -> None:
        tx.run(cast(LiteralString, _MERGE_APPLIES_TO), pairs=pairs)

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
    def _applies_to_pairs(document: ParsedDocument) -> list[dict]:
        return [
            {"from": rule.id, "to": resource_type}
            for rule in document.policy_rules
            for resource_type in rule.resource_types
        ]

    @staticmethod
    def _batched(rows: list) -> list[list]:
        return [rows[i : i + _BATCH_SIZE] for i in range(0, len(rows), _BATCH_SIZE)]
