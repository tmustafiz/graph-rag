from typing import LiteralString, cast

from neo4j import Driver, ManagedTransaction

from graph_rag.ingest.parsed_document import ParsedDocument

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
    def _chunk_pairs(document: ParsedDocument) -> list[dict]:
        # section_id embeds a zero-padded index, so this sort is full document reading order.
        ordered = sorted(document.chunks, key=lambda c: (c.section_id, c.order))
        return [{"from": a.id, "to": b.id} for a, b in zip(ordered, ordered[1:], strict=False)]

    @staticmethod
    def _batched(rows: list) -> list[list]:
        return [rows[i : i + _BATCH_SIZE] for i in range(0, len(rows), _BATCH_SIZE)]
